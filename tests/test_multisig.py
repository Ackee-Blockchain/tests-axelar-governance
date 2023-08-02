import logging
import random
from collections import defaultdict
from typing import List, Set, DefaultDict

from woke.testing import *
from woke.testing.fuzzing import *
from pytypes.source.contracts.governance.Multisig import Multisig
from pytypes.tests.PayloadReceiverMock import PayloadReceiverMock


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class MultisigFuzzTest(FuzzTest):
    _multisig: Multisig
    _threshold: int
    _payload_receivers: List[PayloadReceiverMock]
    _signers: Set[Account]
    _signatures: DefaultDict[bytes, Set[Account]]

    _last_payloads: DefaultDict[PayloadReceiverMock, bytes]
    _last_values: DefaultDict[PayloadReceiverMock, int]

    _payloads: List[bytes]
    _native_values: List[int]

    def pre_sequence(self) -> None:
        a = default_chain.accounts[0]

        accounts = random.sample(default_chain.accounts, random_int(1, len(default_chain.accounts)))
        self._threshold = random_int(1, len(accounts))
        self._multisig = Multisig.deploy(
            accounts,
            self._threshold,
            from_=a,
        )
        self._payload_receivers = [PayloadReceiverMock.deploy(from_=a) for _ in range(5)]
        self._signers = set(accounts)
        self._signatures = defaultdict(set)
        self._last_payloads = defaultdict(bytes)
        self._last_values = defaultdict(int)

        self._payloads = [b""] + [random_bytes(1, 32) for _ in range(4)]
        self._native_values = [0] + [random_int(1, 1000) for _ in range(4)]

    @flow()
    def flow_sign_execute(self) -> None:
        target = random.choice(self._payload_receivers)
        payload = random.choice(self._payloads)
        native_value = random.choice(self._native_values)
        caller = random_account()

        caller_balance = caller.balance
        multisig_balance = self._multisig.balance
        target_balance = target.balance

        calldata = Abi.encode_call(Multisig.execute, [target, payload, native_value])

        if caller not in self._signers:
            with must_revert(Multisig.NotSigner()):
                self._multisig.transact(calldata, from_=caller)
        elif caller in self._signatures[calldata]:
            with must_revert(Multisig.AlreadyVoted()):
                self._multisig.transact(calldata, from_=caller)
        elif len(self._signatures[calldata]) + 1 == self._threshold:
            caller.balance += native_value
            tx = self._multisig.transact(calldata, value=native_value, from_=caller)
            assert Multisig.MultisigOperationExecuted(keccak256(calldata)) in tx.events

            assert caller.balance == caller_balance
            assert self._multisig.balance == multisig_balance
            assert target.balance == target_balance + native_value
            assert target.lastPayload() == payload
            assert target.lastValue() == native_value

            self._signatures[calldata].clear()

            self._last_payloads[target] = payload
            self._last_values[target] = native_value

            logger.info(f"{caller} executed {calldata} with value {native_value}")
        else:
            tx = self._multisig.transact(calldata, from_=caller)
            assert len(tx.events) == 0

            assert target.lastPayload() == self._last_payloads[target]
            assert target.lastValue() == self._last_values[target]

            self._signatures[calldata].add(caller)

    @flow()
    def flow_sign_rotate(self) -> None:
        accounts = sorted(random.sample(default_chain.accounts, random_int(1, len(default_chain.accounts))))
        threshold = random_int(1, len(accounts))

        calldata = Abi.encode_call(Multisig.rotateSigners, [accounts, threshold])
        caller = random_account()

        with may_revert() as e:
            tx = self._multisig.transact(calldata, from_=caller)

        if caller not in self._signers:
            assert e.value == Multisig.NotSigner()
        elif caller in self._signatures[calldata]:
            assert e.value == Multisig.AlreadyVoted()
        else:
            assert e.value is None
            if len(self._signatures[calldata]) + 1 == self._threshold:
                assert Multisig.MultisigOperationExecuted(keccak256(calldata)) in tx.events
                self._signatures.clear()
                self._signers = set(accounts)
                self._threshold = threshold

                logger.info(f"{caller} rotated signers to {accounts} with threshold {threshold}")
            else:
                self._signatures[calldata].add(caller)
                assert len(tx.events) == 0

                #logger.info(f"{caller} signed {calldata}")



@default_chain.connect()
def test_multisig():
    MultisigFuzzTest().run(10, 10_000)
