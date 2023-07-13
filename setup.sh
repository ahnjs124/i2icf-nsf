#!/bin/bash
firewall=$(ip route get 8.8.8.8 | awk -F"src " 'NR==1{split($2,a," ");print a[1]}')
sed -i  "s/10.0.0.5/${firewall}/" ~/firewall/confd.conf

sudo tc qdisc add dev ens3 ingress
sudo tc filter add dev ens3 ingress protocol mpls_uc flower action mpls pop protocol ipv4 action pass