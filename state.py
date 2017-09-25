import rlp
from utils import normalize_address, hash32, trie_root, \
    big_endian_int, address, int256, encode_hex, encode_int, \
    big_endian_to_int, int_to_addr, parse_as_bin, parse_as_int, \
    decode_hex, sha3, is_string, is_numeric
from rlp.sedes import big_endian_int, Binary, binary, CountableList
import utils
import trie
from trie import Trie
from securetrie import SecureTrie
from config import default_config, Env
from db import BaseDB, EphemDB, OverlayDB, RefcountDB
import copy
from account import Account
import sys

STATE_DEFAULTS = {
    "txindex": 0,
    "gas_used": 0,
    "gas_limit": 3141592,
    "block_number": 0,
    "block_coinbase": '\x00' * 20,
    "block_difficulty": 1,
    "timestamp": 0,
    "logs": [],
    "receipts": [],
    "bloom": 0,
    "suicides": [],
    "recent_uncles": {},
    "prev_headers": [],
    "refunds": 0,
}

class State():
    def __init__(self, root=b'', env=Env(), executing_on_head=False, **kwargs):
        self.env = env
        self.trie = SecureTrie(Trie(RefcountDB(self.db), root))
        for k, v in STATE_DEFAULTS.items():
            setattr(self, k, kwargs.get(k, copy.copy(v)))
        self.journal = []
        self.cache = {}
        self.log_listeners = []
        self.deletes = []
        self.changed = {}
        self.executing_on_head = executing_on_head

    @property
    def db(self):
        return self.env.db

    @property
    def config(self):
        return self.env.config

    def get_block_hash(self, n):
        if self.block_number < n or n > 256 or n < 0:
            o = b'\x00' * 32
        else:
            o = self.prev_headers[n].hash if self.prev_headers[n] else b'\x00' * 32
        return o

    def add_block_header(self, block_header):
        self.prev_headers = [block_header] + self.prev_headers

    def get_and_cache_account(self, address):
        if address in self.cache:
            return self.cache[address]
        if self.executing_on_head and False:
            try:
                rlpdata = self.db.get(b'address:' + address)
            except KeyError:
                rlpdata = b''
        else:
            rlpdata = self.trie.get(address)
        if rlpdata != trie.BLANK_NODE:
            o = rlp.decode(rlpdata, Account, env=self.env, address=address)
        else:
            o = Account.blank_account(
                self.env, address, self.config['ACCOUNT_INITIAL_NONCE'])
        self.cache[address] = o
        o._mutable = True
        o._cached_rlp = None
        return o

    def get_balance(self, address):
        return self.get_and_cache_account(
            utils.normalize_address(address)).balance

    def get_nonce(self, address):
        return self.get_and_cache_account(utils.normalize_address(address)).nonce

    def set_and_journal(self, acct, param, val):
        # self.journal.append((acct, param, getattr(acct, param)))
        preval = getattr(acct, param)
        self.journal.append(lambda: setattr(acct, param, preval))
        setattr(acct, param, val)

    def set_balance(self, address, value):
        acct = self.get_and_cache_account(utils.normalize_address(address))
        self.set_and_journal(acct, 'balance', value)
        self.set_and_journal(acct, 'touched', True)

    def set_code(self, address, value):
        # assert is_string(value)
        acct = self.get_and_cache_account(utils.normalize_address(address))
        self.set_and_journal(acct, 'code', value)
        self.set_and_journal(acct, 'touched', True)

    def set_nonce(self, address, value):
        acct = self.get_and_cache_account(utils.normalize_address(address))
        self.set_and_journal(acct, 'nonce', value)
        self.set_and_journal(acct, 'touched', True)

    def increment_nonce(self, address):
        address = utils.normalize_address(address)
        acct = self.get_and_cache_account(address)
        newnonce = acct.nonce + 1
        self.set_and_journal(acct, 'nonce', newnonce)
        self.set_and_journal(acct, 'touched', True)

    def account_exists(self, address):
        a = self.get_and_cache_account(address)
        if a.deleted and not a.touched:
            return False
        if a.touched:
            return True
        else:
            return a.existent_at_start
        return o

    def transfer_value(self, from_addr, to_addr, value):
        assert value >= 0
        if self.get_balance(from_addr) >= value:
            self.delta_balance(from_addr, -value)
            self.delta_balance(to_addr, value)
            return True
        return False

    def account_to_dict(self, address):
        return self.get_and_cache_account(utils.normalize_address(address)).to_dict()

    def commit(self, allow_empties=False):
        for addr, acct in self.cache.items():
            if acct.touched or acct.deleted:
                acct.commit()
                self.deletes.extend(acct.storage_trie.deletes)
                self.changed[addr] = True
                if self.account_exists(addr) or allow_empties:
                    self.trie.update(addr, rlp.encode(acct))
                    if self.executing_on_head:
                        self.db.put(b'address:' + addr, rlp.encode(acct))
                else:
                    self.trie.delete(addr)
                    if self.executing_on_head:
                        try:
                            self.db.delete(b'address:' + addr)
                        except KeyError:
                            pass
        self.deletes.extend(self.trie.deletes)
        self.trie.deletes = []
        self.cache = {}
        self.journal = []

def prev_header_to_dict(h):
    return {
        "hash": '0x' + encode_hex(h.hash),
        "number": str(h.number),
        "timestamp": str(h.timestamp),
        "difficulty": str(h.difficulty),
        "gas_used": str(h.gas_used),
        "gas_limit": str(h.gas_limit),
        "uncles_hash": '0x' + encode_hex(h.uncles_hash)
    }

BLANK_UNCLES_HASH = sha3(rlp.encode([]))

def dict_to_prev_header(h):
    return FakeHeader(hash=parse_as_bin(h['hash']),
                      number=parse_as_int(h['number']),
                      timestamp=parse_as_int(h['timestamp']),
                      difficulty=parse_as_int(h['difficulty']),
                      gas_used=parse_as_int(h.get('gas_used', '0')),
                      gas_limit=parse_as_int(h['gas_limit']),
                      uncles_hash=parse_as_bin(h.get('uncles_hash', '0x' + encode_hex(BLANK_UNCLES_HASH))))