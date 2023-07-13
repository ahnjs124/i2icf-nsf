"""
*********************************************************************
* NETCONF Notification Streams                                      *
* Python version.                                                   *
*                                                                   *
* (C) 2021 Tail-f Systems                                           *
* Permission to use this code as a starting point hereby granted    *
*                                                                   *
* See the README file for more information                          *
*********************************************************************
"""

from __future__ import print_function
import argparse
import logging
import socket
import select
import datetime as dt
import sys
import textwrap
import requests

import notif_ns as ns
import ietf_i2nsf_monitoring_interface_ns as mi_ns

import _confd
import _confd.dp as dp

from scapy.all import *

xmltag = _confd.XmlTag
value = _confd.Value
tagvalue = _confd.TagValue

log_level = logging.INFO
logging.basicConfig(
    format="%(asctime)s:%(relativeCreated)s"
           "%(levelname)s:%(filename)s:%(lineno)s:%(funcName)s  %(message)s",
    level=log_level)
log = logging.getLogger("confd_example_logger")

flows = {}

class NotifCallbacks(object):
    def cb_get_log_times(self, nctx):
        pass
    def cb_replay(self, nctx, start, stop):
        pass

class flow():
    def __init__(self,src_ip,dst_ip,protocol):
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.protocol = protocol
        self.src_port = []

    def set_port(self,src_port,dst_port):
        self.src_port = src_port
        self.dst_port = dst_port

    def set_first_timestamp(self):
        self.first_timestamp = time.time()

    def get_first_timestamp(self):
        return self.first_timestamp 

    def set_timestamp(self):
        self.last_timestamp = time.time()

    def get_timestamp(self):
        return self.last_timestamp

    def set_count(self,count):
        self.count = count
    
    def add_count(self):
        self.count += 1

    def get_count(self):
        return self.count

    def set_total_bytes(self,total_bytes):
        self.total_bytes = total_bytes

    def add_total_bytes(self,total_bytes):
        self.total_bytes += total_bytes

    def set_metrics(self,duration):
        if duration > 0:
            self.measurement_time = duration
            self.arrival_rate = self.count / duration
            self.arrival_throughput = self.total_bytes / duration
        else:
            self.measurement_time = 0
            self.arrival_rate = 0
            self.arrival_throughput = 0

    def show(self):
        print(f"""        Source IP: {self.src_ip}
        Destination IP: {self.dst_ip}
        Protocol: {self.protocol}
        Last Timestamp: {self.last_timestamp}
        Arrival Rate: {self.arrival_rate}
        Arrival Throughput: {self.arrival_throughput}
        Count: {self.count}
        Total Bytes: {self.total_bytes}
        """)

def detect_flow(packet):
    if IP in packet:
        if packet.haslayer(Raw):
            raw_data = bytes(packet[Raw].load)  # Convert to bytes
            for key in list(flows):
                if flows[key].get_timestamp() + 5 <= time.time():
                    del flows[key]
            if b"GET" in raw_data or b"POST" in raw_data:  # Check for HTTP GET or POST requests
                # Get the source and destination IP addresses
                src_ip = packet[IP].src
                dst_ip = packet[IP].dst
                protocol = packet[IP].get_field('proto')
                if (protocol.i2s[packet[IP].proto] == "tcp"):
                    src_port = packet[TCP].sport
                    dst_port = packet[TCP].dport
                else:
                    src_port = 0
                    dst_port = 0
                # Create a unique key for the combination of source and destination IP addresses
                key = (src_ip, dst_ip, protocol.i2s[packet[IP].proto],dst_port)

                # Get the current timestamp
                timestamp = time.time()

                # Check if the key exists in the dictionary
                if key in flows:
                    # Check if the last packet was received within the time window (5 second)
                    if timestamp - flows[key].get_timestamp() <= 5:
                        # Increment the packet count
                        flows[key].add_count()
                        # Increment the total bytes
                        flows[key].add_total_bytes(len(packet)) 
                    else:
                        # Reset the packet count, total bytes, and update the last timestamp
                        flows[key].set_count(1)
                        flows[key].set_total_bytes(len(packet))
                        flows[key].set_timestamp()
                        flows[key].set_metrics(0)
                else:
                    # Add a new entry for the key in the dictionary
                    flows[key] = flow(src_ip,dst_ip,protocol.i2s[packet[IP].proto])
                    flows[key].set_port(src_port,dst_port)
                    flows[key].set_count(1)
                    flows[key].set_total_bytes(len(packet))
                    flows[key].set_first_timestamp()
                    flows[key].set_timestamp()
                    flows[key].set_metrics(0)

                duration = timestamp - flows[key].get_timestamp() # Calculate the duration of the time window

                if duration > 0:
                    flows[key].set_metrics(duration)

def get_date_time():
    now = dt.datetime.now()
    ConfdNow = _confd.DateTime(
        year=now.year,
        month=now.month,
        day=now.day,
        hour=now.hour,
        min=now.minute,
        sec=now.second,
        micro=now.microsecond,
        timezone=0,
        timezone_minutes=0)
    return ConfdNow


def send_notifup(livectx, index, flags1, flags2):
    Now = get_date_time()
    ret = [
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_up),
                 value((ns.ns.notif_link_up, ns.ns.hash),
                       _confd.C_XMLBEGIN)
                 ),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_if_index),
                 value(index, _confd.C_UINT32)),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_property),
                 value((ns.ns.notif_link_property, ns.ns.hash),
                       _confd.C_XMLBEGIN)
                 ),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_flags),
                 value(flags1, _confd.C_UINT32)),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_property),
                 value((ns.ns.notif_link_property, ns.ns.hash),
                       _confd.C_XMLEND)
                 ),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_property),
                 value((ns.ns.notif_link_property, ns.ns.hash),
                       _confd.C_XMLBEGIN)
                 ),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_flags),
                 value(flags2, _confd.C_UINT32)),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_property),
                 value((ns.ns.notif_link_property, ns.ns.hash),
                       _confd.C_XMLEND)
                 ),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_up),
                 value((ns.ns.notif_link_up, ns.ns.hash),
                       _confd.C_XMLEND)
                 )
    ]
    dp.notification_send(livectx, Now, ret)
    log.debug("notif up sent")


def send_notifdown(livectx, index):
    Now = get_date_time()
    ret = [
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_down),
                 value((ns.ns.notif_link_down, ns.ns.hash),
                       _confd.C_XMLBEGIN)
                 ),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_if_index),
                 value(index, _confd.C_UINT32)),
        tagvalue(xmltag(ns.ns.hash,
                        ns.ns.notif_link_down),
                 value((ns.ns.notif_link_down, ns.ns.hash),
                       _confd.C_XMLEND)
                 )
    ]
    dp.notification_send(livectx, Now, ret)
    log.debug("notif down sent")

def send_notif_ddos(livectx,index):
    Now = get_date_time()
    ret = [
        tagvalue(xmltag(mi_ns.ns.hash,
                mi_ns.ns.i2nsfmi_i2nsf_nsf_event),
            value((mi_ns.ns.i2nsfmi_i2nsf_nsf_event, mi_ns.ns.hash),
                _confd.C_XMLBEGIN)
            ),

            tagvalue(xmltag(mi_ns.ns.hash,
                    mi_ns.ns.i2nsfmi_i2nsf_nsf_detection_ddos),
                value((mi_ns.ns.i2nsfmi_i2nsf_nsf_detection_ddos, mi_ns.ns.hash),
                    _confd.C_XMLBEGIN)
                ),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_attack_type),
                    value((mi_ns.ns.hash, mi_ns.ns.i2nsfmi_syn_flood), _confd.C_IDENTITYREF)),

            tagvalue(xmltag(mi_ns.ns.hash,
                    mi_ns.ns.i2nsfmi_i2nsf_nsf_detection_ddos),
                value((mi_ns.ns.i2nsfmi_i2nsf_nsf_detection_ddos, mi_ns.ns.hash),
                    _confd.C_XMLEND)
                ),

        tagvalue(xmltag(mi_ns.ns.hash,
                mi_ns.ns.i2nsfmi_i2nsf_nsf_event),
            value((mi_ns.ns.i2nsfmi_i2nsf_nsf_event, mi_ns.ns.hash),
                _confd.C_XMLEND)
            )
    ]
    dp.notification_send(livectx, Now, ret)
    log.debug("notif ddos sent")

def send_flows(livectx,interface,src_ip,dst_ip,protocol,src_port,dst_port,measurement_time,arrival_rate,arrival_throughput):
    Now = get_date_time()
    if protocol =="tcp":
        proto = mi_ns.ns.i2nsfmi_tcp
    elif protocol == "icmp":
        proto = mi_ns.ns.i2nsfmi_icmp
    x = requests.get(url='http://10.0.0.58:5000/session/get',json={"ip":src_ip},headers={"Content-Type":"application/json"})
    ret = [
        tagvalue(xmltag(mi_ns.ns.hash,
                mi_ns.ns.i2nsfmi_i2nsf_event),
            value((mi_ns.ns.i2nsfmi_i2nsf_event, mi_ns.ns.hash),
                _confd.C_XMLBEGIN)
            ),

            tagvalue(xmltag(mi_ns.ns.hash,
                    mi_ns.ns.i2nsfmi_i2nsf_traffic_flows),
                value((mi_ns.ns.i2nsfmi_i2nsf_traffic_flows, mi_ns.ns.hash),
                    _confd.C_XMLBEGIN)
                ),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_interface_name),
                    value(interface, _confd.C_BUF)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_interface_type),
                    value(mi_ns.ns.i2nsfmi_ingress, _confd.C_ENUM_HASH)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_src_ip),
                    value(src_ip, _confd.C_IPV4)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_dst_ip),
                    value(dst_ip, _confd.C_IPV4)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_protocol),
                    value((mi_ns.ns.hash, proto), _confd.C_IDENTITYREF)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_src_port),
                    value(x.json(), _confd.C_UINT16)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_dst_port),
                    value(dst_port, _confd.C_UINT16)),
                    

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_measurement_time),
                    value(measurement_time, _confd.C_UINT32)),

                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_arrival_rate),
                    value(arrival_rate, _confd.C_UINT64)),
                    
                tagvalue(xmltag(mi_ns.ns.hash,
                        mi_ns.ns.i2nsfmi_arrival_throughput),
                    value(arrival_throughput, _confd.C_UINT64)),

            tagvalue(xmltag(mi_ns.ns.hash,
                    mi_ns.ns.i2nsfmi_i2nsf_traffic_flows),
                value((mi_ns.ns.i2nsfmi_i2nsf_traffic_flows, mi_ns.ns.hash),
                    _confd.C_XMLEND)
                ),

        tagvalue(xmltag(mi_ns.ns.hash,
                mi_ns.ns.i2nsfmi_i2nsf_event),
            value((mi_ns.ns.i2nsfmi_i2nsf_event, mi_ns.ns.hash),
                _confd.C_XMLEND)
            )
    ]
    dp.notification_send(livectx, Now, ret)
    log.debug("notif flow sent")

def notif_loop():
    csocket = socket.socket()
    wsocket = socket.socket()
    ctx = dp.init_daemon("notifier")
    dp.connect(dx=ctx,
               sock=csocket,
               type=dp.CONTROL_SOCKET,
               ip='127.0.0.1',
               port=4565)
    dp.connect(dx=ctx,
               sock=wsocket,
               type=dp.WORKER_SOCKET,
               ip='127.0.0.1',
               port=4565)
    ncbs = NotifCallbacks()
    livectx = dp.register_notification_stream(ctx, ncbs, wsocket, 'I2NSF-Monitoring')
    dp.register_done(ctx)
    log.debug("register_done called")

    _r = [csocket, sys.stdin]
    _w = []
    _e = []
    last_delivery_time = time.time()
    t = AsyncSniffer(iface="ens3", prn=detect_flow, filter="tcp and not port 5000", store=0)
    t.start()
    while (True):
        if last_delivery_time + 5 < time.time():
            last_delivery_time = time.time()
            flows2 = flows.copy()
            for key,value in flows2.items():
                send_flows(livectx,"ens3",value.src_ip,value.dst_ip,value.protocol,value.src_port,value.dst_port,value.measurement_time,value.arrival_rate,value.arrival_throughput)
                print(f"{value.src_ip}: {value.first_timestamp}")
                print(flows)
        (r, w, e) = select.select(_r, _w, _e, 1)
        for rs in r:
            if rs.fileno() == csocket.fileno():
                try:
                    dp.fd_ready(ctx, csocket)
                except (_confd.error.Error) as e:
                    if e.confd_errno is _confd.ERR_EXTERNAL:
                        log.debug("csocket> " + str(e))
                    else:
                        raise e
            elif rs == sys.stdin:
                input = sys.stdin.readline().rstrip()
                if input == "exit":
                    log.debug("Bye!")
                    return False
                else:
                    if input == "u" or input == "up":
                        send_notifup(livectx, 1, 2112, 32)
                    elif input == "d" or input == "down":
                        #send_notif_ddos(livectx, "test")
                        for key,value in flows.items():
                            send_flows(livectx,"ens3",value.src_ip,value.dst_ip,value.protocol,value.src_port,value.dst_port,value.measurement_time,value.arrival_rate,value.arrival_throughput)
                            print(value.first_timestamp)
                            print(flows)
                        
    t.stop()
    wsocket.close()
    csocket.close()
    dp.release_daemon(ctx)

if __name__ == "__main__":
    debug_levels = {
        's': _confd.SILENT,
        'd': _confd.DEBUG,
        't': _confd.TRACE,
        'p': _confd.PROTO_TRACE,
    }
    parser = argparse.ArgumentParser(
        description="",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-dl', '--debuglevel', choices=debug_levels.keys(),
                        help=textwrap.dedent(
                            '''\
                        set the debug level:
                            s = silent (i.e. no) debug
                            d = debug level debug
                            t = trace level debug
                            p = proto level debug
                        '''))
    args = parser.parse_args()
    confd_debug_level = debug_levels.get(args.debuglevel, _confd.TRACE)
    _confd.set_debug(confd_debug_level, sys.stderr)

    notif_loop()