# Woke tests for Axelar CGP governance submodule

## Setup

1. Clone this repository
2. `git submodule update --init --recursive` if not cloned with `--recursive`
3. `cd source && npm install && cd ..` to install dependencies
4. `woke init pytypes` to generate pytypes
5. `woke test` to run tests

Tested with `woke` version `3.5.0` and `anvil` version `0.1.0 (25d3ce7 2023-08-01T00:20:13.496244391Z)`.
Some of the tests expect a local full node at `http://localhost:8545` with the Ethereum mainnet at block `17435092` running.