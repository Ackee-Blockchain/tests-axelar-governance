import logging
import random
from dataclasses import dataclass
from typing import Dict, Set
from woke.testing import *
from woke.testing.fuzzing import *
from pytypes.axelarnetwork.axelargmpsdksolidity.contracts.interfaces.IAxelarExecutable import IAxelarExecutable

from pytypes.source.contracts.governance.InterchainGovernance import InterchainGovernance
from pytypes.axelarnetwork.axelargmpsdksolidity.contracts.test.MockGateway import MockGateway
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


class InterchainGovernanceFuzzTest(FuzzTest):
    _command_counter: int
    _gateways: Dict[Chain, MockGateway]
    _governance_mocks: Dict[Chain, GovernanceMock]
    _minimal_etas: Dict[Chain, uint256]
    _governances: Dict[Chain, InterchainGovernance]
    _proposals: Dict[Chain, Set[Proposal]]
    _payload_receivers: Dict[Chain, List[PayloadReceiverMock]]

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
        self._governances = {
            chain1: InterchainGovernance.deploy(
                self._gateways[chain1],
                "chain2",
                str(self._governance_mocks[chain2].address),
                self._minimal_etas[chain1],
                from_=a,
                chain=chain1,
            ),
            chain2: InterchainGovernance.deploy(
                self._gateways[chain2],
                "chain1",
                str(self._governance_mocks[chain1].address),
                self._minimal_etas[chain2],
                from_=a,
                chain=chain2,
            ),
        }
        assert self._governances[chain1].minimumTimeLockDelay() == self._minimal_etas[chain1]
        assert self._governances[chain2].minimumTimeLockDelay() == self._minimal_etas[chain2]
        self._proposals = {
            chain1: set(),
            chain2: set(),
        }
        self._payload_receivers = {
            chain1: [PayloadReceiverMock.deploy(from_=a, chain=chain1) for _ in range(20)],
            chain2: [PayloadReceiverMock.deploy(from_=a, chain=chain2) for _ in range(20)],
        }

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
        schedule_events = [e for e in self._last_relay_tx.events if isinstance(e, InterchainGovernance.ProposalScheduled)]
        assert len(schedule_events) == 1

        with must_revert(InterchainGovernance.TimeLockAlreadyScheduled):
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

        logger.info(f"Proposal scheduled on chain{destination_chain.chain_id}: {proposal}")

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
        cancel_events = [e for e in self._last_relay_tx.events if isinstance(e, InterchainGovernance.ProposalCancelled)]
        assert len(cancel_events) == 1

        self._proposals[destination_chain].remove(proposal)

        with must_revert(InterchainGovernance.InvalidTimeLockHash):
            self._governances[destination_chain].executeProposal(
                proposal.target,
                proposal.calldata,
                proposal.native_value,
                from_=random_account(chain=destination_chain),
            )

        logger.info(f"Proposal cancelled on chain{destination_chain.chain_id}: {proposal}")

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

            logger.info(f"Proposal execution reverted on chain{chain.chain_id}: {proposal}")
        else:
            assert tx.block.timestamp >= proposal.eta
            assert PayloadReceiverMock(proposal.target, chain=chain).lastPayload() == proposal.calldata
            assert PayloadReceiverMock(proposal.target, chain=chain).lastValue() == proposal.native_value

            self._proposals[chain].remove(proposal)

            with must_revert(InterchainGovernance.InvalidTimeLockHash):
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
def test_interchain_governance():
    InterchainGovernanceFuzzTest().run(10, 10_000)
