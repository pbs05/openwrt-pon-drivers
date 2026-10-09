#!/usr/bin/env python3
"""Exercise the actual packet tap with tagged/untagged captured OMCI PDUs."""
from pathlib import Path
import os
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "src/fmcs_netdev.c").read_text()
start = source.index("static int fmcs_rcv_packet(")
opening = source.index("{", start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == "{") - (source[end] == "}")
    end += 1
function = source[start:end]
fixture = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t __be32;
#define ETH_HLEN 14
#define VLAN_ETH_HLEN 18
#define IFF_UP 1
#define NET_RX_SUCCESS 0
#define pr_debug(...) ((void)0)
#define READ_ONCE(v) (v)
#define cpu_to_be32(v) __builtin_bswap32(v)
struct net_device { char name[16]; int flags; struct { unsigned rx_packets,rx_bytes; } stats; };
struct sk_buff { u8 *head,*data,*mac; size_t len; bool vlan; u16 tci; struct net_device *dev; int protocol; };
struct fmcs_priv { struct net_device *fttr_devs[16]; u16 omci_channel[16]; };
struct packet_type { void *af_packet_priv; };
static u8 delivered[2048]; static size_t delivered_len; static int omci_count, data_count;
static int skb_linearize(struct sk_buff *s) { return 0; }
static bool skb_mac_header_was_set(struct sk_buff *s) { return s->mac != NULL; }
static u8 *skb_mac_header(struct sk_buff *s) { return s->mac; }
static bool skb_vlan_tag_present(struct sk_buff *s) { return s->vlan; }
static u16 skb_vlan_tag_get(struct sk_buff *s) { return s->tci; }
static void fmcs_rx_omci_frame(struct fmcs_priv *p,const u8 *d,size_t n) { memcpy(delivered,d,n);delivered_len=n;omci_count++; }
static struct sk_buff *netdev_alloc_skb(struct net_device *d,size_t n) { struct sk_buff *s=calloc(1,sizeof(*s));s->head=calloc(1,n);s->data=s->head;return s; }
static void skb_reserve(struct sk_buff *s,size_t n) { s->data+=n; }
static void skb_put_data(struct sk_buff *s,const void *d,size_t n) { memcpy(s->data+s->len,d,n);s->len+=n; }
static int eth_type_trans(struct sk_buff *s,struct net_device *d) { return 0; }
static void netif_rx(struct sk_buff *s) { memcpy(delivered,s->data,s->len);delivered_len=s->len;data_count++;free(s->head);free(s); }
static void dev_kfree_skb_any(struct sk_buff *s) { }
'''
checks = r'''
int main(void) {
    struct net_device dev={.name="fttr0"}, sub={.name="fttr1",.flags=IFF_UP};
    struct fmcs_priv priv={.fttr_devs={&sub}};
    struct packet_type pt={.af_packet_priv=&priv};
    u8 tagged[68]={0}, plain[64]={0}, pdu[48]={0};
    for(int i=0;i<48;i++) pdu[i]=(u8)(i*7+1);
    tagged[12]=0x81;tagged[13]=0;tagged[14]=0x20;tagged[15]=1;
    memcpy(tagged+16,pdu,48);memcpy(plain,tagged,12);memcpy(plain+12,pdu,48);
    struct sk_buff s={.head=tagged,.mac=tagged,.data=tagged+14,.len=54};
    fmcs_rcv_packet(&s,&dev,&pt,&dev);
    assert(omci_count==1 && delivered_len==56 && delivered[3]==3 && delivered[7]==1);
    assert(!memcmp(delivered+8,pdu,48));
    s=(struct sk_buff){.head=plain,.mac=plain,.data=plain+14,.len=50,.vlan=true,.tci=0x2001};
    fmcs_rcv_packet(&s,&dev,&pt,&dev);
    assert(omci_count==2 && !memcmp(delivered+8,pdu,48));
    s.len=45;fmcs_rcv_packet(&s,&dev,&pt,&dev);assert(omci_count==2);
    s.len=50;s.tci=0x40fe;fmcs_rcv_packet(&s,&dev,&pt,&dev);assert(omci_count==2);
    s.tci=0x2101;fmcs_rcv_packet(&s,&dev,&pt,&dev);assert(omci_count==2);
    priv.omci_channel[1]=0x101;
    fmcs_rcv_packet(&s,&dev,&pt,&dev);
    assert(omci_count==3 && delivered[7]==1 && !memcmp(delivered+8,pdu,48));
    s.tci=0x2102;fmcs_rcv_packet(&s,&dev,&pt,&dev);assert(omci_count==3);
    // Priority-0 stock GEM envelope 0x101 must reach fttr1, not VID 1.
    tagged[14]=1;tagged[15]=1;s=(struct sk_buff){.head=tagged,.mac=tagged,.data=tagged+14,.len=54};
    fmcs_rcv_packet(&s,&dev,&pt,&dev);
    assert(data_count==1 && delivered_len==64 && !memcmp(delivered+12,pdu,48));
    tagged[14]=0;tagged[15]=1;fmcs_rcv_packet(&s,&dev,&pt,&dev);assert(data_count==1);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    c = Path(directory) / "rx.c"
    binary = Path(directory) / "rx"
    c.write_text(fixture + function + checks)
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wno-unused-parameter", str(c), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("PASS: actual RX tap preserves complete OMCI PDU across VLAN removal, rejects truncation and demuxes stock GEM IDs")
