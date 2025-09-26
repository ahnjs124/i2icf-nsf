###############################################################################
# ConfD Subscriber intro example
# Implements a DHCP server adapter
#
# (C) 2005-2007 Tail-f Systems
# Permission to use this code as a starting point hereby granted
#
# See the README file for more information
###############################################################################
from __future__ import print_function
import os
import socket
import threading
import time

import _confd
import _confd.cdb as cdb
import ietf_i2nsf_nsf_facing_interface_ns as ns
from collections import OrderedDict
value = _confd.Value

### import _confd as cdb
# cdb.connect() → CDB에 연결
# cdb.subscribe() → CDB의 특정 경로를 구독
# cdb.subscribe_done() → 구독 완료 알림
# cdb.read_subscription_socket() → 변경 이벤트 대기
# cdb.get_string(), cdb.get_int32() 등 → CDB에서 실제 값 읽기
# cdb.diff_iterate() → 변경된 부분을 순회하면서 확인

command = {}

def duration2secs(duration):
    duration_string = str(duration)
    # Note that this function is not complete, it only handles seconds
    [seconds, skipped] = duration_string.strip('PT').rsplit('S')
    return seconds


class Subscriber:
    def __init__(self, prio=100, path='/'):
        # CDB(Confd Database)에 subscription을 위한 소켓 생성
        # 이벤트(데이터 변경 알림)가 발생하면 이 소켓을 통해 알림만 받음
        # 즉, self.sock 은 “벨이 울린다” 역할 (이벤트 트리거)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.path = path
        self.prio = prio

        # cdb.connect() → CDB에 연결
        
        # cdb.SUBSCRIPTION_SOCKET 은 ConfD CDB에 “구독(subscribe)”을 할 때 쓰는 전용 소켓 타입 상수
        # 이 소켓은 "구독 전용 소켓"이 됨 (구독설정, 변경 이벤트 수신 대기, 변경된 내용 읽기, 처리 완료 응답)

        # '127.0.0.1': ConfD 프로세스가 같은 서버에서 실행 중
        # _confd.CONFD_PORT: ConfD 데몬이 열고 있는 포트 번호, 보통은 기본값인 4565
        # 구독할 경로(path): CDB 안에서 특정 YANG 데이터 모델의 경로를 지정 ('/' → 루트 전체 구독 (모든 변경 이벤트 받음))
        # 즉, "내 로컬(127.0.0.1)에 실행 중인 ConfD(4565번 포트)에 TCP 연결을 맺고, CDB 전체(/)에 대해 구독 전용 소켓을 열겠다" 는 의미
        cdb.connect(self.sock, cdb.SUBSCRIPTION_SOCKET, '127.0.0.1',
                    _confd.CONFD_PORT, self.path)
        print("● confd Port:", _confd.CONFD_PORT)


        # 특정 namespace, path에 대해 구독 요청
        # ns.ns.hash: 특정 YANG namespace의 식별자 (해시 값)
        # self.prio: 구독자 우선순위(숫자가 작을수록 더 먼저 처리됨)
        # self.path: YANG 데이터 경로 (XPath 형태), '/'는 루트 전체
        cdb.subscribe(self.sock, self.prio, ns.ns.hash, self.path)


        # 구독 절차 완료
        # confD는 여러 번 cdb.subscribe() 를 호출해서 여러 path를 구독할 수 있는데,
        # 마지막에 반드시 subscribe_done() 을 호출해야 “구독 절차가 끝났다”고 인정함
        # 즉, “구독 설정을 다 했어. 이제 이벤트를 보내도 돼!” 라고 ConfD에 알려주는 단계
        cdb.subscribe_done(self.sock)
        print("Subscribed to {path}".format(path=self.path))


    def subscribeloop(self):
        # 변경 대기 → 읽기 → 확인 응답
        self.wait()       # 이벤트가 올 때까지 블로킹
        self.read_confd() # 실제로 무엇이 바뀌었는지 읽어 처리
        self.ack()        # "처리 완료"를 ConfD에 통지


    # 이벤트가 올 때까지 블로킹
    def wait(self):
        # subscription 이벤트 발생 대기
        cdb.read_subscription_socket(self.sock) #구독한 path에서 무언가 바뀌면 반환


    # "처리 완료"를 ConfD에 통지
    def ack(self):
        # 이벤트 처리 완료 알림
        cdb.sync_subscription_socket(self.sock, cdb.DONE_PRIORITY)



    # 실제로 무엇이 바뀌었는지 읽어 처리
    def read_confd(self):
        # ConfD 설계 자체가 "이벤트 알림 전용 소켓(sock)과 데이터 소켓(rsock)을 따로 쓴다.
        # 구독 소켓(self.sock) 은 이벤트 알림 전용 → lightweight, 빠른 신호
        # 데이터 소켓(rsock) 은 실제 데이터 읽기/쓰기 전용 → 트랜잭션 세션 기반

        # 이미 구독 중인 self.sock에서 이벤트를 받았을 때, CDB에서 정책 데이터를 확인하려고 추가로 여는 소켓
        # 즉,구독중인 self.sock에서 알림이 왔을 때, rsock는 실제로 CDB 안의 데이터를 읽으려고 새로 연결하는 소켓
        rsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)

        
        # READ_SOCKET으로 CDB 연결
        cdb.connect(rsock, cdb.READ_SOCKET, '127.0.0.1',
                    _confd.CONFD_PORT, '/')
        

         # 현재 실행 중인 정책(RUNNING datastore) 을 읽겠다
        cdb.start_session(rsock, cdb.RUNNING)
                
        # CDB의 XPath 경로에서 prefix 없이 쓰인 노드를 올바르게 해석하려면, namespace를 미리 지정해줘야 합니다.
        # ns.ns.hash는 해당 YANG 모듈(namespace)의 고유 식별 해시값
        # 같은 경로에서 i2nsf-security-policy 노드를 어느 YANG 모듈에서 찾아야 할지 ConfD가 알게 됩니다.
        # 즉, "이 소켓에서 하는 질의들은 이 네임스페이스(YANG 모듈) 기준이다" 라고 선언하는 단계
        cdb.set_namespace(rsock, ns.ns.hash)
        

        ##### 이 블록은 정책 개수 → 각 정책 이름 → 룰 개수 → 각 룰의 이름/우선순위/조건(IP/포트) → iptables 커맨드 누적 순서로 읽어옵니다.

        # cdb.num_instances(sock, <path>): 해당 path가 가리키는 YANG 노드가 list일 때, 그 list 안에 몇 개의 인스턴스가 있는지를 세어주는 함수
        # 즉,num_instances로 최상위 컨테이너 /i2nsf-security-policy의 인스턴스 개수를 구함
        policy_num = cdb.num_instances(rsock,"/i2nsf-security-policy")
        print("selected policy num:", policy_num)


        for i in range (0,policy_num):
            #cdb.cd(rsock, "/i2nsf-security-policy[{index}]".format(index=i))

            # 특정 인덱스에 있는 정책의 name 값을 읽어오는 것
            name = cdb.get(rsock, "/i2nsf-security-policy[{index_i}]/name".format(index_i=i))
            print(f"name: {name}")


            # 현재 policy의 rules
            rules = cdb.num_instances(rsock,"/i2nsf-security-policy[{index_i}]/rules".format(index_i=i))


            for j in range (0,rules):
                #cdb.cd(rsock,"rules[{index}]".format(index=j))
                rule_name = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/name".format(index_i=i,index_j=j))
                print(f"rule-name: {rule_name}")
                if cdb.exists(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/priority".format(index_i=i,index_j=j)):
                    priority = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/priority".format(index_i=i,index_j=j)).as_pyval()
                else:
                    priority = 1
                command[priority] = f"iptables -I FORWARD"

                #CONDITION CHECK
                if cdb.exists(rsock, "/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4".format(index_i=i,index_j=j)):
                    if cdb.exists(rsock, "/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/destination-ipv4-range".format(index_i=i,index_j=j)):
                        destination_ipv4_range = cdb.num_instances(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/destination-ipv4-range".format(index_i=i,index_j=j))
                        for ip in range(0,destination_ipv4_range):
                            #cdb.cd(rsock,"condition/ipv4/destination-ipv4-range[{index}]".format(index=ip))
                            start = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/destination-ipv4-range[{index_ip}]/start".format(index_i=i,index_j=j,index_ip=ip))
                            end = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/destination-ipv4-range[{index_ip}]/end".format(index_i=i,index_j=j,index_ip=ip))
                            dst_ip_command = f" -d {start}"

                            command[priority] = command[priority] + dst_ip_command

                            print(f"destination_ipv4_range: [{start} {end}]")
                    
                    if cdb.exists(rsock, "/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/source-ipv4-range".format(index_i=i,index_j=j)):
                        source_ipv4_range = cdb.num_instances(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/source-ipv4-range".format(index_i=i,index_j=j))
                        for ip in range(0,source_ipv4_range):
                            #cdb.cd(rsock,"condition/ipv4/destination-ipv4-range[{index}]".format(index=ip))
                            start = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/source-ipv4-range[{index_ip}]/start".format(index_i=i,index_j=j,index_ip=ip))
                            end = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/ipv4/source-ipv4-range[{index_ip}]/end".format(index_i=i,index_j=j,index_ip=ip))
                            src_ip_command = f" -s {start}"

                            command[priority] = command[priority] + src_ip_command

                            print(f"source_ipv4_range: [{start} {end}]")
                
                if cdb.exists(rsock, "/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/tcp".format(index_i=i,index_j=j)):
                    if cdb.exists(rsock, "/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/tcp/destination-port-number".format(index_i=i,index_j=j)):
                        tcp_port = cdb.num_instances(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/tcp/destination-port-number/port-numbers".format(index_i=i,index_j=j))
                
                        for tcp in range(0,tcp_port):
                            #cdb.cd(rsock,"condition/tcp/destination-port-number/port-numbers[{index}]".format(index=ip))

                            dst_port = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/condition/tcp/destination-port-number/port-numbers[{index_port}]/start".format(index_i=i,index_j=j,index_port=ip))
                            dst_port_command = f" -p tcp -m tcp --dport {dst_port}"

                            command[priority] = command[priority] + dst_port_command

                
                
                #ACTION CHECK
                
                ingress_action = cdb.get(rsock,"/i2nsf-security-policy[{index_i}]/rules[{index_j}]/action/packet-action/ingress-action".format(index_i=i,index_j=j))
                print(f"ingress_action: {ingress_action}")


                if ingress_action == value((ns.ns.hash, ns.ns.i2nsfnfi_pass), _confd.C_IDENTITYREF):
                    action_command = " -j ACCEPT"
                    command[priority] = command[priority] + action_command

                elif ingress_action == value((ns.ns.hash, ns.ns.i2nsfnfi_drop), _confd.C_IDENTITYREF):
                    action_command = " -j DROP"
                    command[priority] = command[priority] + action_command
            #print(command)


        sortedCommand = OrderedDict(sorted(command.items(), key=lambda t: t[0]))


        for keys,values in sortedCommand.items():
            os.system(values)
        #os.system(f"iptables -A FORWARD -s {start}/32 -j ACCEPT")

        # default_lease_time = cdb.get(rsock, "/dhcp/default-lease-time")
        # max_lease_time = cdb.get(rsock, "/dhcp/max-lease-time")
        # log_facility = cdb.get(rsock, "/dhcp/log-facility")

        # if log_facility == ns.dhcpd_kern:
        #     log_facility_string = "log-facility kern"
        # if log_facility == ns. dhcpd_mail:
        #     log_facility_string = "log-facility mail"
        # if log_facility == ns.dhcpd_local7:
        #     log_facility_string = "log-facility local7"

        # self.fp = open("dhcpd.conf.tmp", "w")
        # self.fp.write("default-lease-time {dlt}\n"
        #               "max-lease-time {mlt}\n"
        #               "{lfs}\n".format(dlt=duration2secs(default_lease_time),
        #                                mlt=duration2secs(max_lease_time),
        #                                lfs=log_facility_string))

        # sub_nets = cdb.num_instances(
        #     rsock,
        #     "/dhcp/subnets/subnet")
        # for i in range(0, sub_nets):
        #     cdb.cd(rsock, "/dhcp/subnets/subnet[{index}]".format(index=i))
        #     self.do_subnet(rsock)

        # shared_networks = cdb.num_instances(
        #     rsock,
        #     "/dhcp/shared-networks/shared-network"
        # )
        # for i in range(0, shared_networks):
        #     sh_net = "/dhcp/shared-networks/shared-network[{0}]".format(str(i))
        #     network_name = cdb.get(
        #         rsock,
        #         sh_net + "/name"
        #     )

        #     self.fp.write("shared-network {0} {{\n".format(str(network_name)))

        #     m = cdb.num_instances(
        #         rsock,
        #         sh_net + "/subnets/subnet")
        #     for j in range(0, m):
        #         cdb.pushd(rsock, sh_net +
        #                   "/subnets/subnet[{0}]".format(str(j)))
        #         self.do_subnet(rsock)
        #         cdb.popd(rsock)

        #     self.fp.write("}\n")
        # self.fp.close()

        return cdb.close(rsock)

    def do_subnet(self, rsock):
        net = cdb.get(rsock, "net")
        mask = cdb.get(rsock, "mask")

        self.fp.write("subnet {net} netmask {netmask} {{\n".format(
            net=str(net), netmask=str(mask)))

        if cdb.exists(rsock, "range"):
            self.fp.write(" range ")
            dynamic_bootp = cdb.get(rsock, "range/dynamic-bootp")
            if dynamic_bootp:
                self.fp.write(" dynamic-bootp ")
            low_addr = cdb.get(rsock, "range/low-addr")
            hi_addr = cdb.get(rsock, "range/hi-addr")
            self.fp.write(" {low}  {high} \n".format(
                low=str(low_addr),
                high=str(hi_addr)
            ))

        if cdb.exists(rsock, "routers"):
            routers = cdb.get(rsock, "routers")
            comma_routers = str(routers).replace(" ", ",")
            self.fp.write(" option routers {0}\n".format(comma_routers))

        mlt = cdb.get(rsock, "max-lease-time")
        self.fp.write(" max-lease-time {0}\n}};\n".format(duration2secs(mlt)))


def run():
    # Setup subscription
    sub = Subscriber(10, '/i2nsf-security-policy')

    # Read Initial config
    #sub.read_confd()

    def subscriberfun():
        while (True):
            #os.rename("dhcpd.conf.tmp", "dhcpd.conf")
            # This is the place to HUP the daemon
            sub.subscribeloop()
            print("Configuration applied to firewall")

    threading.Thread(target=subscriberfun).start()

    try:
        while (True):
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nCtrl-C pressed\n")


if __name__ == "__main__":
    run()

