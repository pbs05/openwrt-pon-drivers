// SPDX-License-Identifier: GPL-2.0-only
/*
 * H3C HM2004-DU Micro-OLT Virtual Network Interfaces:
 * - molt_omci: OMCI control channel
 * - molt_ploam: PLOAM control channel
 * - fttr1 ~ fttr16: Downstream DSA switch ports (1:1 mapped to ONU 1~16)
 */

#include <linux/netdevice.h>
#include <linux/etherdevice.h>
#include <linux/skbuff.h>
#include <linux/if_vlan.h>
#include <linux/if_arp.h>
#include "fmcs.h"

struct fmcs_fttr_port_priv {
	struct fmcs_priv *priv;
	u32 port_idx; /* 1-based port index: 1..16 */
};

static netdev_tx_t fmcs_omci_xmit(struct sk_buff *skb, struct net_device *dev)
{
	struct fmcs_priv *priv = *(struct fmcs_priv **)netdev_priv(dev);
	struct net_device *dst_dev;
	u32 msg_type, onu_id;
	u16 vlan_tci;

	dev->stats.tx_packets++;
	dev->stats.tx_bytes += skb->len;

	/*
	 * The OMCI transport uses an 8-byte header:
	 * [0..3]: htonl(3) (OMCI frame type)
	 * [4..7]: htonl(onu_id)
	 * [8..55]: 48-byte OMCI payload
	 */
	if (skb->len < 8) {
		dev_kfree_skb_any(skb);
		return NETDEV_TX_OK;
	}

	msg_type = be32_to_cpup((__be32 *)skb->data);
	onu_id = be32_to_cpup((__be32 *)(skb->data + 4));

	if (msg_type == 3 && onu_id <= 15 && skb->len == 56 &&
	    !skb_linearize(skb)) {
		/* Find destination master ethernet interface: fttr0 is the FPGA SerDes link */
		dst_dev = dev_get_by_name(&init_net, "fttr0");

		if (dst_dev) {
			/* Allocate fresh skb with headroom for 16-byte header */
			u32 omci_len = skb->len - 8;
			struct sk_buff *nskb = alloc_skb(16 + omci_len + 32, GFP_ATOMIC);
			if (nskb) {
				u8 *p;
				skb_reserve(nskb, 2); /* align IP/payload */
				p = skb_put(nskb, 16 + omci_len);

				/* Dest MAC: AA:AA:AA:AA:AA:AA */
				memset(p, 0xaa, 6);
				/* Src MAC: 55:55:55:55:55:55 */
				memset(p + 6, 0x55, 6);
				/* EtherType: 0x8100 (802.1Q) */
				p[12] = 0x81;
				p[13] = 0x00;
				/* VLAN TCI: Priority=1 (0x2000) | ONU_ID */
				vlan_tci = READ_ONCE(priv->omci_channel[onu_id]);
				vlan_tci = 0x2000 | (vlan_tci ? vlan_tci : onu_id);
				p[14] = (u8)(vlan_tci >> 8);
				p[15] = (u8)(vlan_tci & 0xff);

				/* Copy 48-byte OMCI payload */
				memcpy(p + 16, skb->data + 8, omci_len);

				/* HSGMII TX pads the proprietary envelope to 68 bytes.
				 * A 64-byte baseline envelope was observed to receive no reply.
				 * Padding follows the OMCI CRC and is not part of the PDU.
				 */
				if (nskb->len < 68)
					skb_put_zero(nskb, 68 - nskb->len);

				nskb->dev = dst_dev;
				skb_reset_mac_header(nskb);
				skb_reset_network_header(nskb);
				nskb->protocol = htons(0x88b5);
				pr_debug("fmcs: OMCI TX fttr0 onu_id %u len %u\n", onu_id, nskb->len);
				dev_queue_xmit(nskb);
			}
			dev_put(dst_dev);
		}
	}

	(void)priv;
	dev_kfree_skb_any(skb);
	return NETDEV_TX_OK;
}

static void fmcs_ploam_tx_work(struct work_struct *work)
{
	struct fmcs_priv *priv = container_of(work, struct fmcs_priv, ploam_tx_work);
	struct sk_buff *skb;

	while ((skb = skb_dequeue(&priv->ploam_tx_queue))) {
		if (fmcs_spi_send_ploam(priv, skb->data, skb->len))
			priv->ploam_dev->stats.tx_errors++;
		dev_kfree_skb(skb);
	}
}

static netdev_tx_t fmcs_ploam_xmit(struct sk_buff *skb, struct net_device *dev)
{
	struct fmcs_priv *priv = *(struct fmcs_priv **)netdev_priv(dev);

	dev->stats.tx_packets++;
	dev->stats.tx_bytes += skb->len;

	/* ndo_start_xmit runs in atomic context; SPI controller locks sleep. */
	if (priv && atomic_read(&priv->fpga_status) == FMCS_FPGA_STATUS_READY &&
	    skb->len == 13 && skb_queue_len(&priv->ploam_tx_queue) < 64 &&
	    !skb_linearize(skb)) {
		skb_queue_tail(&priv->ploam_tx_queue, skb);
		schedule_work(&priv->ploam_tx_work);
		return NETDEV_TX_OK;
	}

	dev->stats.tx_dropped++;
	dev_kfree_skb_any(skb);
	return NETDEV_TX_OK;
}

static netdev_tx_t fmcs_fttr_xmit(struct sk_buff *skb, struct net_device *dev)
{
	struct fmcs_fttr_port_priv *port_priv = netdev_priv(dev);
	struct net_device *dst_dev;
	u16 vlan_tci;

	dev->stats.tx_packets++;
	dev->stats.tx_bytes += skb->len;

	dst_dev = dev_get_by_name(&init_net, "fttr0");
	if (dst_dev) {
		/* The priority-0 envelope identifies GEM port 0x100 + ONU-ID. */
		vlan_tci = (u16)((0x100 + port_priv->port_idx) & 0x0fff);
		skb = vlan_insert_tag(skb, htons(ETH_P_8021Q), vlan_tci);
		if (skb && !skb_put_padto(skb, 68)) {
			skb->dev = dst_dev;
			dev_queue_xmit(skb);
		}
		dev_put(dst_dev);
		return NETDEV_TX_OK;
	}

	dev_kfree_skb_any(skb);
	return NETDEV_TX_OK;
}

static int fmcs_fttr_open(struct net_device *dev)
{
	/* Carrier state is maintained externally by ONU O5 link status */
	return 0;
}

static int fmcs_fttr_stop(struct net_device *dev)
{
	return 0;
}

static const struct net_device_ops fmcs_omci_ops = {
	.ndo_start_xmit = fmcs_omci_xmit,
};

static const struct net_device_ops fmcs_ploam_ops = {
	.ndo_start_xmit = fmcs_ploam_xmit,
};

static const struct net_device_ops fmcs_fttr_ops = {
	.ndo_open       = fmcs_fttr_open,
	.ndo_stop       = fmcs_fttr_stop,
	.ndo_start_xmit = fmcs_fttr_xmit,
	.ndo_set_mac_address = eth_mac_addr,
	.ndo_validate_addr   = eth_validate_addr,
};

void fmcs_rx_omci_frame(struct fmcs_priv *priv, const u8 *data, size_t len)
{
	struct sk_buff *skb;

	if (!priv->omci_dev || !(priv->omci_dev->flags & IFF_UP))
		return;

	skb = netdev_alloc_skb(priv->omci_dev, len + 2);
	if (!skb)
		return;

	skb_reserve(skb, 2);
	skb_put_data(skb, data, len);
	skb->dev = priv->omci_dev;
	skb_reset_mac_header(skb);
	skb->protocol = htons(ETH_P_802_2);

	priv->omci_dev->stats.rx_packets++;
	priv->omci_dev->stats.rx_bytes += len;
	netif_rx(skb);
}

void fmcs_rx_ploam_frame(struct fmcs_priv *priv, const u8 *data, size_t len)
{
	struct sk_buff *skb;

	if (!priv->ploam_dev || !(priv->ploam_dev->flags & IFF_UP))
		return;

	skb = netdev_alloc_skb(priv->ploam_dev, len + 2);
	if (!skb)
		return;

	skb_reserve(skb, 2);
	skb_put_data(skb, data, len);
	skb->dev = priv->ploam_dev;
	skb_reset_mac_header(skb);
	skb->protocol = htons(ETH_P_802_2);

	priv->ploam_dev->stats.rx_packets++;
	priv->ploam_dev->stats.rx_bytes += len;
	netif_rx(skb);
}

static int fmcs_rcv_packet(struct sk_buff *skb, struct net_device *dev,
			   struct packet_type *pt, struct net_device *orig_dev)
{
	struct fmcs_priv *priv = (struct fmcs_priv *)pt->af_packet_priv;
	u16 vlan_tci, vlan_id, priority;
	u16 onu_id;
	const u8 *eth_hdr;
	u8 eth_buf[VLAN_ETH_HLEN];
	int mac_len;
	size_t total_len;

	if (!dev || strcmp(dev->name, "fttr0") != 0)
		goto out;

	if (!priv)
		goto out;

	if (!skb_mac_header_was_set(skb))
		goto out;
	eth_hdr = skb_mac_header(skb);
	if (eth_hdr < skb->head || eth_hdr > skb->data)
		goto out;
	mac_len = skb->data - eth_hdr;
	total_len = mac_len + skb->len;
	if (total_len < ETH_HLEN)
		goto out;
	eth_hdr = skb_header_pointer(skb, -mac_len,
				     min_t(size_t, total_len, sizeof(eth_buf)),
				     eth_buf);
	if (!eth_hdr)
		goto out;

	if (skb_vlan_tag_present(skb)) {
		vlan_tci = skb_vlan_tag_get(skb);
	} else if (total_len >= 16 && eth_hdr[12] == 0x81 && eth_hdr[13] == 0x00) {
		vlan_tci = (eth_hdr[14] << 8) | eth_hdr[15];
	} else {
		goto out;
	}

	priority = (vlan_tci >> 13) & 0x07;
	vlan_id = vlan_tci & 0x0fff;
	onu_id = vlan_id;
	if (vlan_id >= 0x100 && vlan_id <= 0x10f &&
	    READ_ONCE(priv->omci_channel[vlan_id - 0x100]) == vlan_id)
		onu_id = vlan_id - 0x100;

	/* Priority 1 (0x2000): OMCI response frame from sub-gateway */
	if (priority == 1 && onu_id <= 15) {
		int omci_offset;
		u8 omci_buf[56];

		if (skb_vlan_tag_present(skb)) {
			/* This FPGA envelope has no inner Ethernet EtherType: OMCI
			 * starts immediately after TCI at byte 16. VLAN untagging
			 * removes four bytes, leaving the first two OMCI bytes in
			 * the Ethernet h_proto field, before skb->data.
			 */
			if (total_len < 12 + 48)
				goto out;
			omci_offset = 12;
		} else {
			if (total_len < 16 + 48)
				goto out;
			omci_offset = 16;
		}

		/*
		 * Deliver 56-byte frame to molt_omci:
		 * [0..3]: htonl(3)
		 * [4..7]: htonl(mapped ONU-ID)
		 * [8..55]: 48-byte OMCI payload
		 */
		*(__be32 *)&omci_buf[0] = cpu_to_be32(3);
		*(__be32 *)&omci_buf[4] = cpu_to_be32(onu_id);
		if (skb_copy_bits(skb, omci_offset - mac_len,
				  &omci_buf[8], 48))
			goto out;

		pr_debug("fmcs: OMCI RX fttr0 onu_id %u len %zu\n", onu_id, sizeof(omci_buf));
		fmcs_rx_omci_frame(priv, omci_buf, sizeof(omci_buf));
		goto out;
	}

	/* Priority 0: GEM 0x101..0x10f for the verified ONU-ID 1..15 slots. */
	if (priority == 0 && vlan_id >= 0x101 && vlan_id <= 0x10f) {
		struct net_device *sub_dev = priv->fttr_devs[vlan_id - 0x101];
		if (sub_dev && (sub_dev->flags & IFF_UP)) {
			if (!skb_vlan_tag_present(skb) && total_len < VLAN_ETH_HLEN)
				goto out;
			/* Packet taps share the skb with the original RX path. Only
			 * clone its descriptor; keep GRO/GSO fragments and metadata.
			 */
			skb = skb_share_check(skb, GFP_ATOMIC);
			if (!skb)
				return NET_RX_DROP;
			skb_push_rcsum(skb, mac_len);
			if (skb_vlan_pop(skb))
				goto out;
			skb_scrub_packet(skb, false);
			skb->dev = sub_dev;
			skb->protocol = eth_type_trans(skb, sub_dev);
			skb_postpull_rcsum(skb, skb_mac_header(skb), ETH_HLEN);
			sub_dev->stats.rx_packets++;
			sub_dev->stats.rx_bytes += skb->len;
			netif_rx(skb);
			return NET_RX_SUCCESS;
		}
	}

out:
	/* Packet taps own a reference even when the frame is ignored. */
	dev_kfree_skb_any(skb);
	return NET_RX_SUCCESS;
}

int fmcs_netdevs_init(struct fmcs_priv *priv)
{
	int ret;
	int i;
	u8 base_mac[ETH_ALEN];

	skb_queue_head_init(&priv->ploam_tx_queue);
	INIT_WORK(&priv->ploam_tx_work, fmcs_ploam_tx_work);

	/* Create molt_omci */
	priv->omci_dev = alloc_netdev(sizeof(struct fmcs_priv *), "molt_omci",
				      NET_NAME_UNKNOWN, ether_setup);
	if (!priv->omci_dev)
		return -ENOMEM;

	priv->omci_dev->netdev_ops = &fmcs_omci_ops;
	priv->omci_dev->type = ARPHRD_NONE;
	priv->omci_dev->hard_header_len = 0;
	priv->omci_dev->header_ops = NULL;
	priv->omci_dev->flags = IFF_NOARP;
	*(struct fmcs_priv **)netdev_priv(priv->omci_dev) = priv;
	eth_hw_addr_random(priv->omci_dev);

	ret = register_netdev(priv->omci_dev);
	if (ret) {
		free_netdev(priv->omci_dev);
		priv->omci_dev = NULL;
		return ret;
	}

	/* Create molt_ploam */
	priv->ploam_dev = alloc_netdev(sizeof(struct fmcs_priv *), "molt_ploam",
				       NET_NAME_UNKNOWN, ether_setup);
	if (!priv->ploam_dev) {
		unregister_netdev(priv->omci_dev);
		free_netdev(priv->omci_dev);
		priv->omci_dev = NULL;
		return -ENOMEM;
	}

	priv->ploam_dev->netdev_ops = &fmcs_ploam_ops;
	priv->ploam_dev->type = ARPHRD_NONE;
	priv->ploam_dev->hard_header_len = 0;
	priv->ploam_dev->header_ops = NULL;
	priv->ploam_dev->flags = IFF_NOARP;
	*(struct fmcs_priv **)netdev_priv(priv->ploam_dev) = priv;
	eth_hw_addr_random(priv->ploam_dev);

	ret = register_netdev(priv->ploam_dev);
	if (ret) {
		free_netdev(priv->ploam_dev);
		priv->ploam_dev = NULL;
		unregister_netdev(priv->omci_dev);
		free_netdev(priv->omci_dev);
		priv->omci_dev = NULL;
		return ret;
	}

	/* Generate a deterministic base MAC for downstream FTTR switch ports */
	eth_random_addr(base_mac);
	base_mac[0] = 0x02;
	base_mac[1] = 0xFE;
	base_mac[2] = 0x88;
	base_mac[3] = 0x75;
	base_mac[4] = 0x81;

	/* Create downstream DSA-style switch ports fttr1 ~ fttr16 */
	for (i = 0; i < FMCS_MAX_FTTR_PORTS; i++) {
		char ifname[IFNAMSIZ];
		struct net_device *dev;
		struct fmcs_fttr_port_priv *port_priv;

		snprintf(ifname, sizeof(ifname), "fttr%d", i + 1);
		dev = alloc_netdev(sizeof(struct fmcs_fttr_port_priv), ifname,
				   NET_NAME_UNKNOWN, ether_setup);
		if (!dev) {
			ret = -ENOMEM;
			goto err_unreg_fttr;
		}

		dev->netdev_ops = &fmcs_fttr_ops;
		dev->priv_flags &= ~IFF_TX_SKB_SHARING;
		port_priv = netdev_priv(dev);
		port_priv->priv = priv;
		port_priv->port_idx = i + 1;

		/* Set unique MAC: 02:FE:88:75:81:01 ~ 10 */
		base_mac[5] = (u8)(i + 1);
		eth_hw_addr_set(dev, base_mac);

		/* Default carrier is OFF until ONU establishes O5 link */
		netif_carrier_off(dev);

		ret = register_netdev(dev);
		if (ret) {
			free_netdev(dev);
			goto err_unreg_fttr;
		}

		priv->fttr_devs[i] = dev;
	}

	/* Hook RX packets from fttr0 */
	priv->fttr_pt.type = htons(ETH_P_ALL);
	priv->fttr_pt.dev = NULL;
	priv->fttr_pt.af_packet_net = &init_net;
	priv->fttr_pt.ignore_outgoing = true;
	priv->fttr_pt.func = fmcs_rcv_packet;
	priv->fttr_pt.af_packet_priv = priv;
	dev_add_pack(&priv->fttr_pt);

	return 0;

err_unreg_fttr:
	while (--i >= 0) {
		if (priv->fttr_devs[i]) {
			unregister_netdev(priv->fttr_devs[i]);
			free_netdev(priv->fttr_devs[i]);
			priv->fttr_devs[i] = NULL;
		}
	}
	unregister_netdev(priv->ploam_dev);
	free_netdev(priv->ploam_dev);
	priv->ploam_dev = NULL;
	unregister_netdev(priv->omci_dev);
	free_netdev(priv->omci_dev);
	priv->omci_dev = NULL;
	return ret;
}

void fmcs_netdevs_exit(struct fmcs_priv *priv)
{
	int i;

	dev_remove_pack(&priv->fttr_pt);

	for (i = 0; i < FMCS_MAX_FTTR_PORTS; i++) {
		if (priv->fttr_devs[i]) {
			unregister_netdev(priv->fttr_devs[i]);
			free_netdev(priv->fttr_devs[i]);
			priv->fttr_devs[i] = NULL;
		}
	}

	if (priv->ploam_dev) {
		unregister_netdev(priv->ploam_dev);
		cancel_work_sync(&priv->ploam_tx_work);
		skb_queue_purge(&priv->ploam_tx_queue);
		free_netdev(priv->ploam_dev);
		priv->ploam_dev = NULL;
	}
	if (priv->omci_dev) {
		unregister_netdev(priv->omci_dev);
		free_netdev(priv->omci_dev);
		priv->omci_dev = NULL;
	}
}
