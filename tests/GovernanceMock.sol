// SPDX-License-Identifier: MIT

import "@axelar-network/axelar-gmp-sdk-solidity/contracts/interfaces/IAxelarGateway.sol";

contract GovernanceMock {
    IAxelarGateway public immutable gateway;

    constructor(address gateway_) {
        gateway = IAxelarGateway(gateway_);
    }

    function scheduleProposal(
        string calldata destinationChain,
        string calldata contractAddress,
        address target,
        bytes calldata callData,
        uint256 nativeValue,
        uint256 eta
    ) external {
        bytes memory payload = abi.encode(0, target, callData, nativeValue, eta);
        gateway.callContract(destinationChain, contractAddress, payload);
    }

    function cancelProposal(
        string calldata destinationChain,
        string calldata contractAddress,
        address target,
        bytes calldata callData,
        uint256 nativeValue
    ) external {
        bytes memory payload = abi.encode(1, target, callData, nativeValue);
        gateway.callContract(destinationChain, contractAddress, payload);
    }

    function approveMultisig(
        string calldata destinationChain,
        string calldata contractAddress,
        address target,
        bytes calldata callData,
        uint256 nativeValue
    ) external {
        bytes memory payload = abi.encode(2, target, callData, nativeValue);
        gateway.callContract(destinationChain, contractAddress, payload);
    }

    function cancelMultisigApproval(
        string calldata destinationChain,
        string calldata contractAddress,
        address target,
        bytes calldata callData,
        uint256 nativeValue
    ) external {
        bytes memory payload = abi.encode(3, target, callData, nativeValue);
        gateway.callContract(destinationChain, contractAddress, payload);
    }
}
