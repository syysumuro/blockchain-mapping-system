# -*- coding: utf-8 -*-

import select
import socket
import sys
import Queue
from transactions import Transaction
from block import Block
import chain
import time
from config import Env
from db import LevelDB
from chain_service import ChainService
import select, socket, sys, Queue
import struct
import os
import glob
import rlp
from keystore import Keystore
from consensus import Consensus
from map_reply import MapReplyRecord, LocatorRecord, Response
from ipaddress import IPv4Network, IPv6Network, IPv4Address, IPv6Address
from p2p import P2P


HOST = ''
REC_PORT = 16001
SND_PORT = 16002


def open_sockets():
    try:
        rec_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        snd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print 'Socket created'
    except socket.error, msg:
        print 'Failed to create socket. Error Code : ' + str(msg[0]) + ' Message ' + msg[1]
        sys.exit(1)
    # Bind socket to local host and port
    try:
        rec_socket.bind((HOST, REC_PORT))
    except socket.error:
        print 'Bind failed.'
        sys.exit(1)

    print 'Socket bind complete in ports ' + str(REC_PORT) + ' and ' + str(SND_PORT)

    return rec_socket, snd_socket


# reads the fields nonce, AFI and the IP from the socket
def read_socket(rec_socket):
    nonce = rec_socket.recv(64)
    afi = rec_socket.recv(16)
    if (afi == '1'*16):
        # address IPv4
        address = IPv4Address(rec_socket.recv(32))
    elif (afi == '2'*16):
        # address IPv6
        address = IPv6Address(rec_socket.recv(128))
    else:
        rec_socket.recv(1024)  # used to empty socket
        raise Exception('Incorrect AFI read from socket')
    return nonce, afi, address


def write_socket(res, snd_socket):
    snd_socket.sendto(res, (HOST, SND_PORT))


def test_map_reply():
    locator = LocatorRecord(priority=0, weight=0, mpriority=0, mweight=0, unusedflags=0, LpR=0,
                            locator=IPv4Address(u'192.168.0.1'))
    locators = []
    locators.append(locator)
    reply = MapReplyRecord(eid_prefix=IPv4Network(u'192.168.1.0/24'), locator_records=locators)
    print(reply.to_bitstream())


def init_chain():
    db = LevelDB("./chain")
    env = Env(db)
    return ChainService(env)


def init_p2p(last_block_num):
    # P2P initialization
    p2p = P2P(last_block_num)
    while (p2p.bootstrap()):
        time.sleep(1)
    return p2p


def init_consensus():
    return Consensus()


def init_keystore(keys_dir='./Tests/keystore/'):
    keys = []
    for file in glob.glob(os.path.join(keys_dir, '*')):
        keys.append(Keystore.load(keys_dir + file[-40:], "TFG1234"))
    return keys


def run():
    chain = init_chain()
    p2p = init_p2p(chain.get_head_block().header.number)
    consensus = init_consensus()
    keys = init_keystore()
    end = 0
    myIPs = chain.get_own_ips(keys[0].address)

    while(not end):
        
        try:
            #Process new blocks
            try:
                block = p2p.get_block()
                while block is not None:
                    signer = consensus.get_next_signer()
                    res = chain.verify_block_signature(block, signer)
                    if res:
                        # correct block
                        chain.add_block(block)
                        myIPs = chain.get_own_ips(keys[0].address)
                        timestamp = chain.get_head_block().get_timestamp()
                        consensus.calculate_next_signer(myIPs, timestamp)
                    block = p2p.get_block()
            except Exception as e:
                print "Exception while processing a received block"
                print e
        
            #Process transactions from the network
            try:
                tx_ext = p2p.get_tx()
                while tx_ext is not None:
                    res = chain.add_pending_transaction(tx_ext)
                    if res:
                        #correct tx
                        p2p.broadcast_tx(tx_ext)
                    #get new transactions to process
                    tx_ext = p2p.get_tx()
            except Exception as e:
                print "Exception while processing a received transaction"
                print e


            #Check if the node has to sign the next block
            try:
                me, signer = consensus.amISigner(myIPs)
                if me:
                    new_block = chain.create_block(signer)
                    #Like receiving a new block
                    chain.add_block(new_block)
                    myIPs = chain.get_own_ips(keys[0].address)
                    timestamp = chain.get_head_block().get_timestamp()
                    consensus.calculate_next_signer(myIPs, timestamp)
                    p2p.broadcast_block(new_block)
            except Exception as e:
                print "Exception while checkinf if the node has to sign the next block"
                print e

            #Process transactions from the user
            try:
                tx_int = user.get_tx()
                if tx_int is not None:
                    res = chain.add_pending_transaction(tx_int)
                    if res:
                        #correct tx
                        p2p.broadcast_tx(tx_int)
            except:
                print "Exception while processing transactions from the user"
                print e  

            #answer queries from OOR
            try:
                query = oor.get_query()
                if query is not None:
                    info = chain.query_eid(query)
                    oor.send(info)
            except:
                print "Exception while answering queries from OOR"
                print e  

            #answer queries from the network
            #blocks
            try:
                block_numbers = p2p.get_block_queries()
                if block_numbers is not None:
                    response = []
                    for block in block_numbers:
                        response.append(chain.get_block(block))
                    p2p.answer_block_queries(response)
            except:
                print "Exception while answering queries from the network"
                print e  

                
            #transaction pool
            try:
                if p2p.tx_pool_query():
                    pool = chain.get_transaction_pool()
                    p2p.answer_tx_pool_query(pool)
            except:
                print "Exception while answering the transaction pool"
                print e  

        except Exception as e:
            print e
            # Stop P2P
            p2p.stop()
            sys.exit(0)


if __name__ == "__main__":
    run()

    """
    keys = init_keystore()
    chain = init_chain()
    chain.query_eid(keys[0].keystore['address'], IPv4Address('192.168.0.1'))
    """
    rec_socket, snd_socket = open_sockets()
    mrr = LocatorRecord()
    r = Response(nonce=12345678, flag=0,info=mrr)
    while 1:
        res = rec_socket.recvfrom(50)[0]
        if res is not None:
            print(struct.pack('>I',(int(struct.unpack("I",res[0:4])[0]))).encode('HEX'))
            print(struct.pack('>I',(int(struct.unpack("I",res[4:8])[0]))).encode('HEX'))
            afi = int(struct.unpack("H",res[8:10])[0])
            if afi == 1:
                ip = IPv4Address(res[18:])
                print(ip)
            elif afi == 2:
                ip = IPv6Address(res[18:])
                print(ip)
            msg = struct.pack('>I',(int(struct.unpack("I",res[0:4])[0]))) + struct.pack('>I',(int(struct.unpack("I",res[4:8])[0]))) + struct.pack('H',int(struct.unpack("H",res[8:10])[0]))
            write_socket(msg,snd_socket)
        time.sleep(0.5)
    