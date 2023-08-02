from woke.testing import *
from pytypes.source.contracts.interfaces.IAxelarGateway import IAxelarGateway
from pytypes.source.contracts.AxelarGateway import AxelarGateway
from pytypes.source.contracts.interfaces.IGovernable import IGovernable
from pytypes.source.contracts.governance.AxelarServiceGovernance import AxelarServiceGovernance


@default_chain.connect(fork="http://localhost:8545")
def test_axelar_gateway_upgrade():
    a, b, c, d = default_chain.accounts[:4]
    default_chain.set_default_accounts(a)

    proxy = IAxelarGateway("0x4F4495243837681061C4743b74B3eEdf548D56A5")
    impl = AxelarGateway.deploy(proxy.authModule(), proxy.tokenDeployer())

    governance = AxelarServiceGovernance.deploy(proxy, "mainnet", "", 0, [a, b, c], 2)

    admin_epoch = proxy.adminEpoch()
    admins = proxy.admins(admin_epoch)

    for admin in admins:
        tx = proxy.upgrade(impl, keccak256(impl.code), Abi.encode(["address", "address", "bytes"], [governance, a, b""]), from_=admin)
        if any(len(e.topics) > 0 and e.topics[0] == b'\xbc|\xd7Z \xee\'\xfd\x9a\xde\xba\xb3 A\xf7U!M\xbck\xff\xa9\x0c\xc0"[9\xda.\\-;' for e in tx.raw_events):
            break

    governable = IGovernable(proxy)
    assert governable.governance() == governance.address
    assert governable.mintLimiter() == a.address
    assert proxy.implementation() == impl.address

    new_impl = AxelarGateway.deploy(proxy.authModule(), proxy.tokenDeployer())
    calldata = Abi.encode_call(proxy.upgrade, [new_impl, keccak256(new_impl.code), b""])

    with must_revert(AxelarServiceGovernance.NotSigner):
        governance.executeMultisigProposal(proxy, calldata, 0, from_=d)

    command_id = b"\x00" * 32
    payload = Abi.encode(
        ["uint256", "address", "bytes", "uint256", "uint256"],
        [2, proxy, calldata, 0, 0],
    )

    # need to mock approve the next execute call on AxelarGateway
    # heuristics: request access lists for both validateContractCall and isContractCallApproved
    #             the difference between the two is the storage slot that needs to be set to 1 (isApproved - true)
    access_list1, _ = proxy.validateContractCall(command_id, "mainnet", "", keccak256(payload), request_type="access_list")
    access_list2, _ = proxy.isContractCallApproved(command_id, "mainnet", "", governance, keccak256(payload), request_type="access_list")
    storage_slots = set(access_list2[proxy.address]) - set(access_list1[proxy.address])
    assert len(storage_slots) == 1
    default_chain.chain_interface.set_storage_at(str(proxy.address), next(iter(storage_slots)), int.to_bytes(1, 32, "big"))
    governance.execute(
        command_id,
        "mainnet",
        "",
        payload,
    )

    governance.executeMultisigProposal(proxy, calldata, 0, from_=a)
    assert proxy.implementation() == impl.address
    governance.executeMultisigProposal(proxy, calldata, 0, from_=c)
    assert proxy.implementation() == new_impl.address

