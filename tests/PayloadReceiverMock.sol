// SPDX-License-Identifier: MIT

contract PayloadReceiverMock {
    bytes public lastPayload;
    uint256 public lastValue;

    fallback(bytes calldata payload) external payable returns (bytes memory) {
        lastPayload = payload;
        lastValue = msg.value;
    }
}