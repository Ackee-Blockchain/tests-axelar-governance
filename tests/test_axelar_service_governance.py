from collections import defaultdict
from dataclasses import dataclass
import logging
import random
from typing import Dict, Set, DefaultDict
from woke.testing import *
from woke.testing.fuzzing import *

from pytypes.axelarnetwork.axelargmpsdksolidity.contracts.interfaces.IAxelarExecutable import IAxelarExecutable
from pytypes.axelarnetwork.axelargmpsdksolidity.contracts.test.MockGateway import MockGateway
from pytypes.source.contracts.governance.AxelarServiceGovernance import AxelarServiceGovernance
from pytypes.tests.GovernanceMock import GovernanceMock
from pytypes.tests.PayloadReceiverMock import PayloadReceiverMock

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


chain1 = Chain()
chain2 = Chain()


@dataclass(frozen=True)
class Proposal:
    target: Address
    calldata: bytes
    native_value: uint256
    eta: uint256


@dataclass(frozen=True)
class MultisigProposal:
    target: Address
    calldata: bytes
    native_value: uint256


class AxelarServiceGovernanceFuzzTest(FuzzTest):
    _command_counter: int
    _gateways: Dict[Chain, MockGateway]
    _governance_mocks: Dict[Chain, GovernanceMock]
    _minimal_etas: Dict[Chain, uint256]
    _governances: Dict[Chain, AxelarServiceGovernance]
    _proposals: Dict[Chain, Set[Proposal]]
    _payload_receivers: Dict[Chain, List[PayloadReceiverMock]]

    _thresholds: Dict[Chain, int]
    _signers: Dict[Chain, Set[Account]]
    _signatures: Dict[Chain, Dict[bytes, Set[Account]]]
    _last_payloads: DefaultDict[PayloadReceiverMock, bytes]
    _last_values: DefaultDict[PayloadReceiverMock, int]
    _execute_proposals: Dict[Chain, Set[MultisigProposal]]
    _execute_approvals: Dict[Chain, Dict[bytes, MultisigProposal]]

    _payloads: List[bytes]
    _native_values: List[int]

    def _relay(self, tx: TransactionAbc) -> None:
        a = chain1.accounts[0].address

        for index, event in enumerate(tx.raw_events):
            if len(event.topics) == 0:
                continue

            if event.topics[0] == MockGateway.ContractCall.selector:
                sender = Abi.decode(["address"], event.topics[1])[0]
                destination_chain_name, destination_address_str, payload = Abi.decode(
                    ["string", "string", "bytes"], event.data
                )
                destination_chain = chain2 if destination_chain_name == "chain2" else chain1
                destination_gw = self._gateways[destination_chain]
                source_chain_name = "chain1" if destination_chain_name == "chain2" else "chain2"
                command_id = self._command_counter.to_bytes(32, "big")

                destination_gw.approveContractCall(Abi.encode(
                    ["string", "string", "address", "bytes32", "bytes32", "uint256"],
                    [source_chain_name, str(sender), Address(destination_address_str), event.topics[2], bytes.fromhex(tx.tx_hash[2:]), index]
                ), command_id, from_=a)

                self._last_relay_tx = IAxelarExecutable(destination_address_str, chain=destination_chain).execute(
                    command_id,
                    source_chain_name,
                    str(sender),
                    payload,
                    from_=a,
                )
                self._command_counter += 1
            elif event.topics[0] == MockGateway.ContractCallWithToken.selector:
                sender = Abi.decode(["address"], event.topics[1])[0]
                destination_chain_name, destination_address_str, payload, symbol, amount = Abi.decode(
                    ["string", "string", "bytes", "string", "uint256"], event.data
                )
                destination_chain = chain2 if destination_chain_name == "chain2" else chain1
                destination_gw = self._gateways[destination_chain]
                source_chain_name = "chain1" if destination_chain_name == "chain2" else "chain2"
                command_id = self._command_counter.to_bytes(32, "big")

                destination_gw.approveContractCallWithMint(Abi.encode(
                    ["string", "string", "address", "bytes32", "string", "uint256", "bytes32", "uint256"],
                    [source_chain_name, str(sender), Address(destination_address_str), event.topics[2], symbol, amount, bytes.fromhex(tx.tx_hash[2:]), index]
                    ), command_id, from_=a)

                self._last_relay_tx = IAxelarExecutable(destination_address_str, chain=destination_chain).executeWithToken(
                    command_id,
                    source_chain_name,
                    str(sender),
                    payload,
                    symbol,
                    amount,
                    from_=a,
                )
                self._command_counter += 1

    def pre_sequence(self) -> None:
        self._command_counter = 0
        chain1.tx_callback = self._relay
        chain2.tx_callback = self._relay

        assert chain1.accounts[0].address == chain2.accounts[0].address
        a = chain1.accounts[0].address

        self._gateways = {
            chain1: MockGateway.deploy(from_=a, chain=chain1),
            chain2: MockGateway.deploy(from_=a, chain=chain2),
        }
        self._governance_mocks = {
            chain1: GovernanceMock.deploy(self._gateways[chain1], from_=a, chain=chain1),
            chain2: GovernanceMock.deploy(self._gateways[chain2], from_=a, chain=chain2),
        }
        self._minimal_etas = {
            chain1: random_int(0, 1_000),
            chain2: random_int(0, 1_000),
        }
        self._signers = {
            chain1: set(random.sample(chain1.accounts, random_int(1, len(chain1.accounts)))),
            chain2: set(random.sample(chain2.accounts, random_int(1, len(chain2.accounts)))),
        }
        self._thresholds = {
            chain1: random_int(1, len(self._signers[chain1])),
            chain2: random_int(1, len(self._signers[chain2])),
        }
        self._governances = {
            chain1: AxelarServiceGovernance.deploy(
                self._gateways[chain1],
                "chain2",
                str(self._governance_mocks[chain2].address),
                self._minimal_etas[chain1],
                list(self._signers[chain1]),
                self._thresholds[chain1],
                from_=a,
                chain=chain1,
            ),
            chain2: AxelarServiceGovernance.deploy(
                self._gateways[chain2],
                "chain1",
                str(self._governance_mocks[chain1].address),
                self._minimal_etas[chain2],
                list(self._signers[chain2]),
                self._thresholds[chain2],
                from_=a,
                chain=chain2,
            ),
        }
        for chain in [chain1, chain2]:
            assert self._governances[chain].minimumTimeLockDelay() == self._minimal_etas[chain]
        self._proposals = {
            chain1: set(),
            chain2: set(),
        }
        self._payload_receivers = {
            chain1: [PayloadReceiverMock.deploy(from_=a, chain=chain1) for _ in range(5)],
            chain2: [PayloadReceiverMock.deploy(from_=a, chain=chain2) for _ in range(5)],
        }
        self._signatures = {
            chain1: defaultdict(set),
            chain2: defaultdict(set),
        }
        self._last_payloads = defaultdict(bytes)
        self._last_values = defaultdict(int)

        self._payloads = [b""] + [random_bytes(1, 32) for _ in range(2)]
        self._native_values = [0] + [random_int(1, 1000) for _ in range(2)]

        self._execute_proposals = {
            chain1: set(),
            chain2: set(),
        }
        self._execute_approvals = {
            chain1: {},
            chain2: {},
        }

    @flow(weight=70)
    def flow_sign_rotate(self) -> None:
        chain = random.choice([chain1, chain2])
        accounts = sorted(random.sample(chain.accounts, random_int(1, len(chain.accounts))))
        threshold = random_int(1, len(accounts))

        calldata = Abi.encode_call(AxelarServiceGovernance.rotateSigners, [accounts, threshold])
        caller = random_account(chain=chain)

        with may_revert() as e:
            tx = self._governances[chain].transact(calldata, from_=caller)

        if caller not in self._signers[chain]:
            assert e.value == AxelarServiceGovernance.NotSigner()
        elif caller in self._signatures[chain][calldata]:
            assert e.value == AxelarServiceGovernance.AlreadyVoted()
        else:
            assert e.value is None
            if len(self._signatures[chain][calldata]) + 1 == self._thresholds[chain]:
                assert AxelarServiceGovernance.MultisigOperationExecuted(keccak256(calldata)) in tx.events
                self._signatures[chain].clear()
                self._signers[chain] = set(accounts)
                self._thresholds[chain] = threshold

                logger.info(f"{caller} rotated signers to {accounts} with threshold {threshold}")
            else:
                self._signatures[chain][calldata].add(caller)
                assert len(tx.events) == 0

                logger.debug(f"{caller} signed rotation to {accounts} with threshold {threshold}")

    @flow()
    def flow_sign_execute(self) -> None:
        chain = random.choice([chain1, chain2])
        target = random.choice(self._payload_receivers[chain])
        payload = random.choice(self._payloads)
        native_value = random.choice(self._native_values)
        caller = random_account(chain=chain)

        caller_balance = caller.balance
        governance_balance = self._governances[chain].balance
        target_balance = target.balance
        proposal_hash = keccak256(Abi.encode_packed(
            ["address", "bytes", "uint256"],
            [target.address, payload, native_value],
        ))
        proposal = MultisigProposal(target.address, bytes(payload), native_value)

        calldata = Abi.encode_call(AxelarServiceGovernance.executeMultisigProposal, [target, payload, native_value])

        if caller not in self._signers[chain]:
            with must_revert(AxelarServiceGovernance.NotSigner()):
                self._governances[chain].transact(calldata, from_=caller)
        elif caller in self._signatures[chain][calldata]:
            with must_revert(AxelarServiceGovernance.AlreadyVoted()):
                self._governances[chain].transact(calldata, from_=caller)
        elif len(self._signatures[chain][calldata]) + 1 == self._thresholds[chain]:
            if proposal_hash not in self._execute_approvals[chain].keys():
                with must_revert(AxelarServiceGovernance.NotApproved()):
                    self._governances[chain].transact(calldata, from_=caller)
            else:
                caller.balance += native_value
                tx = self._governances[chain].transact(calldata, value=native_value, from_=caller)
                assert AxelarServiceGovernance.MultisigOperationExecuted(keccak256(calldata)) in tx.events

                assert caller.balance == caller_balance
                assert self._governances[chain].balance == governance_balance
                assert target.balance == target_balance + native_value
                assert target.lastPayload() == payload
                assert target.lastValue() == native_value

                self._signatures[chain][calldata].clear()
                self._execute_approvals[chain].pop(proposal_hash)
                self._execute_proposals[chain].remove(proposal)

                self._last_payloads[target] = payload
                self._last_values[target] = native_value

                logger.info(f"{caller} executed {payload} with value {native_value} to {target}")
        else:
            tx = self._governances[chain].transact(calldata, from_=caller)
            assert len(tx.events) == 0

            assert target.lastPayload() == self._last_payloads[target]
            assert target.lastValue() == self._last_values[target]

            self._signatures[chain][calldata].add(caller)
            self._execute_proposals[chain].add(proposal)

            logger.debug(f"{caller} signed {payload} with value {native_value} to {target}")

    @flow()
    def flow_approve_multisig(self):
        chains = [chain for chain in [chain1, chain2] if len(self._execute_proposals[chain]) > 0]
        if len(chains) == 0:
            return
        destination_chain = random.choice(chains)
        source_chain = chain1 if destination_chain == chain2 else chain2
        proposal = random.choice(list(self._execute_proposals[destination_chain]))

        self._governance_mocks[source_chain].approveMultisig(
            f"chain{destination_chain.chain_id}",
            str(self._governances[destination_chain].address),
            proposal.target,
            proposal.calldata,
            proposal.native_value,
            from_=random_account(chain=source_chain),
        )

        self._execute_approvals[destination_chain][keccak256(Abi.encode_packed(
            ["address", "bytes", "uint256"],
            [proposal.target, proposal.calldata, proposal.native_value],
        ))] = proposal

        logger.debug(f"approved {proposal.calldata} with value {proposal.native_value} to {proposal.target} on chain{destination_chain.chain_id}")

    @flow()
    def flow_cancel_multisig_approval(self):
        chains = [chain for chain in [chain1, chain2] if len(self._execute_approvals[chain]) > 0]
        if len(chains) == 0:
            return
        destination_chain = random.choice(chains)
        source_chain = chain1 if destination_chain == chain2 else chain2
        proposal_hash = random.choice(list(self._execute_approvals[destination_chain].keys()))
        proposal = self._execute_approvals[destination_chain][proposal_hash]

        self._governance_mocks[source_chain].cancelMultisigApproval(
            f"chain{destination_chain.chain_id}",
            str(self._governances[destination_chain].address),
            proposal.target,
            proposal.calldata,
            proposal.native_value,
            from_=random_account(chain=source_chain),
        )

        self._execute_approvals[destination_chain].pop(proposal_hash)

        logger.debug(f"canceled approval of {proposal.calldata} with value {proposal.native_value} to {proposal.target} on chain{destination_chain.chain_id}")

    @flow()
    def flow_schedule_proposal(self):
        source_chain = random.choice([chain1, chain2])
        destination_chain = chain2 if source_chain == chain1 else chain1

        proposal = Proposal(
            target=random.choice(self._payload_receivers[destination_chain]).address,
            calldata=bytes(random_bytes(0, 100)),
            native_value=random_int(0, 1_000),
            eta=destination_chain.blocks["pending"].timestamp + random_int(-100, 1_000)
        )
        while proposal in self._proposals[destination_chain]:
            proposal = Proposal(
                target=random.choice(self._payload_receivers[destination_chain]).address,
                calldata=bytes(random_bytes(0, 100)),
                native_value=random_int(0, 1_000),
                eta=destination_chain.blocks["pending"].timestamp + random_int(-100, 1_000)
            )

        self._governance_mocks[source_chain].scheduleProposal(
            f"chain{destination_chain.chain_id}",
            str(self._governances[destination_chain].address),
            proposal.target,
            proposal.calldata,
            proposal.native_value,
            proposal.eta,
            from_=random_account(chain=source_chain),
        )
        schedule_events = [e for e in self._last_relay_tx.events if isinstance(e, AxelarServiceGovernance.ProposalScheduled)]
        assert len(schedule_events) == 1

        with must_revert(AxelarServiceGovernance.TimeLockAlreadyScheduled):
            self._governance_mocks[source_chain].scheduleProposal(
                f"chain{destination_chain.chain_id}",
                str(self._governances[destination_chain].address),
                proposal.target,
                proposal.calldata,
                proposal.native_value,
                proposal.eta,
                from_=random_account(chain=source_chain),
            )

        if proposal.eta < self._last_relay_tx.block.timestamp + self._minimal_etas[destination_chain]:
            proposal = Proposal(
                proposal.target,
                proposal.calldata,
                proposal.native_value,
                self._last_relay_tx.block.timestamp + self._minimal_etas[destination_chain],
            )

        self._proposals[destination_chain].add(proposal)

        logger.debug(f"Proposal scheduled on chain{destination_chain.chain_id}: {proposal}")

    @flow()
    def flow_cancel_proposal(self):
        chains = [chain for chain in [chain1, chain2] if len(self._proposals[chain]) > 0]
        if len(chains) == 0:
            return

        destination_chain = random.choice(chains)
        source_chain = chain2 if destination_chain == chain1 else chain1

        proposal = random.choice(list(self._proposals[destination_chain]))

        self._governance_mocks[source_chain].cancelProposal(
            f"chain{destination_chain.chain_id}",
            str(self._governances[destination_chain].address),
            proposal.target,
            proposal.calldata,
            proposal.native_value,
            from_=random_account(chain=source_chain),
        )
        cancel_events = [e for e in self._last_relay_tx.events if isinstance(e, AxelarServiceGovernance.ProposalCancelled)]
        assert len(cancel_events) == 1

        self._proposals[destination_chain].remove(proposal)

        with must_revert(AxelarServiceGovernance.InvalidTimeLockHash):
            self._governances[destination_chain].executeProposal(
                proposal.target,
                proposal.calldata,
                proposal.native_value,
                from_=random_account(chain=destination_chain),
            )

        logger.debug(f"Proposal cancelled on chain{destination_chain.chain_id}: {proposal}")

    @flow()
    def flow_execute_proposal(self):
        chains = [chain for chain in [chain1, chain2] if len(self._proposals[chain]) > 0]
        if len(chains) == 0:
            return

        chain = random.choice(chains)
        proposal = random.choice(list(self._proposals[chain]))

        self._governances[chain].balance += proposal.native_value

        with may_revert() as e:
            tx = self._governances[chain].executeProposal(
                proposal.target,
                proposal.calldata,
                proposal.native_value,
                from_=random_account(chain=chain),
            )

        if e.value is not None:
            assert e.value.tx.block.timestamp < proposal.eta

            logger.debug(f"Proposal execution reverted on chain{chain.chain_id}: {proposal}")
        else:
            assert tx.block.timestamp >= proposal.eta
            assert PayloadReceiverMock(proposal.target, chain=chain).lastPayload() == proposal.calldata
            assert PayloadReceiverMock(proposal.target, chain=chain).lastValue() == proposal.native_value

            self._proposals[chain].remove(proposal)
            self._last_payloads[PayloadReceiverMock(proposal.target, chain=chain)] = proposal.calldata
            self._last_values[PayloadReceiverMock(proposal.target, chain=chain)] = proposal.native_value

            with must_revert(AxelarServiceGovernance.InvalidTimeLockHash):
                self._governances[chain].executeProposal(
                    proposal.target,
                    proposal.calldata,
                    proposal.native_value,
                    from_=random_account(chain=chain),
                )

            logger.info(f"Proposal executed on chain{chain.chain_id}: {proposal}")

    @flow(weight=200)
    def flow_roll_time(self):
        chain = random.choice([chain1, chain2])
        chain.mine(lambda x: x + random_int(1, 1_000))

    @invariant(period=10)
    def invariant_etas(self):
        for chain in [chain1, chain2]:
            governance = self._governances[chain]
            for proposal in self._proposals[chain]:
                assert governance.getProposalEta(
                    proposal.target,
                    proposal.calldata,
                    proposal.native_value
                ) == proposal.eta

                hash = keccak256(Abi.encode_packed(
                    ["address", "bytes", "uint256"],
                    [proposal.target, proposal.calldata, proposal.native_value],
                ))
                assert governance.getTimeLock(hash) == proposal.eta


def revert_handler(e: TransactionRevertedError):
    if e.tx is not None:
        print(e.tx.call_trace)
        print(e.tx.console_logs)


@chain1.connect(chain_id=1)
@chain2.connect(chain_id=2)
@on_revert(revert_handler)
def test_axelar_service_governance():
    AxelarServiceGovernanceFuzzTest().run(10, 50_000)
