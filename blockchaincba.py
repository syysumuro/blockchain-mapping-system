# -*- coding: utf-8 -*-

import select
import socket
import sys
import Queue
from transactions import Transaction
from block import Block
import chain
from config import Env
from db import LevelDB
from chain_service import ChainService
import select, socket, sys, Queue
import struct
import os
import glob
from keystore import Keystore
from consensus import Consensus


def init_chain():
    db = LevelDB("./chain")
    env = Env(db)
    return ChainService(env)


def init_p2p():
    # P2P initialization
    return 0


def init_consensus():
    return Consensus()


def init_keystore(keys_dir='./Tests/keystore/'):
    keys = []
    for file in glob.glob(os.path.join(keys_dir, '*')):
        keys.append(Keystore.load(keys_dir + file[-40:], "TFG1234"))
    return keys


def run():
    chain = init_chain()
    p2p = init_p2p()
    consensus = init_consensus()
    keys = init_keystore()
    end = 0

    while(not end):
        
        #Process a block from the network
        try:
            block = p2p.get_block()
            if block is not None:
                signer = consensus.get_next_signer()
                res = chain.verify_block_signature(block, signer)
                if res:
                    # correct block
                    consensus.store_block(block)
                    #Maybe not necessary, depends on P2P implementation
                    p2p.broadcast_block(block)
                else:
                    #reset consensus alg
                    consensus.calculate_next_signer(None)
        except Exception as e:
            print "Exception while processing a received block"
            print e
     
        #Process a definitive block
        try:
            block = consensus.get_solid_block()
            if block is not None:
                #These blocks are always OK
                #Only needed to validate tx logic (apply.py)
                #For simplicity we assume that the previous validation will never fail
                myIPs = chain.add_block(block)
                consensus.calculate_next_signer(myIPs)
        except Exception as e:
            print "Exception while adding a definitive block"
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
        sign = consensus.amIsinger(myIPs)
        if sign.me is True:
            last_block_hash = consensus.get_last_block_hash()
            #TODO: Do you need transactions in the previous blocks (unconfirmed)? I think so :(
            new_block = chain.create_block(sign.signer,last_block_hash)
            consensus.store_block(new_block)
            p2p.broadcast_block(new_block)

        #Process transactions from the user
        tx_int = user.get_tx()
        if tx_int is not None:
            res = chain.add_pending_transaction(tx_int)
            if res:
                #correct tx
                p2p.broadcast_tx(tx_int)

        #answer queries from OOR
        query = oor.get_query()
        if query is not None:
            info = chain.query_eid(query)
            oor.send(info)


if __name__ == "__main__":
    #init()
    #run()
    keys = init_keystore()
    print(keys[0].keystore['address'])

    chain = init_chain()
    print chain.get_head_block().get_timestamp()

    consensus = init_consensus()
    consensus.calculate_next_signer()
    print consensus.get_next_signer()