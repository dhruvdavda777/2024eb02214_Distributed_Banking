# Distributed Banking System (gRPC + Protocol Buffers)

**Student:** Dhruv Davda  
**BITS ID:** 2024eb02214  
**Email:** 2024eb02214@online.bits-pilani.ac.in

## Files

| File | Purpose |
|---|---|
| `banking.proto` | Service and message definitions (Question 1) |
| `server.py` | gRPC server: AccountService + TransactionService (Question 2) |
| `../2024eb02214_Q3_submission/client.py` | gRPC client: commands for every operation and a full demo (Question 3) |
| `banking_pb2.py`, `banking_pb2_grpc.py` | Code generated from `banking.proto` (do not edit) |
| `requirements.txt` | Python packages |

## Setup (once)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# regenerate the gRPC code after any change to banking.proto:
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. banking.proto
```

## Run

Terminal 1 - server:
```bash
python server.py            # port 50051
```

Terminal 2 - client:
```bash
python ../2024eb02214_Q3_submission/client.py demo                         # full test, incl. error handling
python ../2024eb02214_Q3_submission/client.py balance  U1001
python ../2024eb02214_Q3_submission/client.py deposit  U1001 1000 --note "Salary"
python ../2024eb02214_Q3_submission/client.py withdraw U1002 200  --note "ATM"
python ../2024eb02214_Q3_submission/client.py transfer U1001 U1002 1500 --note "Rent"
python ../2024eb02214_Q3_submission/client.py history  U1001 --limit 5
python ../2024eb02214_Q3_submission/client.py --server 192.168.1.20:50051 balance U1001   # server on another machine
```

Sample accounts: `U1001` Aarav Sharma 5000.00, `U1002` Diya Verma 3000.00, `U1003` Kabir Iyer 500.00 (INR).

## RPCs

| Service | RPC | Request -> Response |
|---|---|---|
| AccountService | `GetBalance` (getBalance) | `GetBalanceRequest` -> `BalanceResponse` |
| AccountService | `UpdateBalance` (updateBalance) | `UpdateBalanceRequest` (CREDIT/DEBIT) -> `BalanceResponse` |
| TransactionService | `InitiateTransfer` (initiateTransfer) | `TransferRequest` -> `TransferResponse` |
| TransactionService | `GetTransactionHistory` (getTransactionHistory) | `TransactionHistoryRequest` -> `TransactionHistoryResponse` |

## Error handling (gRPC status codes)

| Problem | Status code | Example message |
|---|---|---|
| Insufficient funds | `FAILED_PRECONDITION` | Insufficient funds: balance is 500.00 INR, requested 10000.00 INR |
| User does not exist | `NOT_FOUND` | User 'U9999' does not exist |
| Invalid data | `INVALID_ARGUMENT` | Amount must be greater than 0 / at most 2 decimal places / Cannot transfer to the same account / user_id is required / Update type must be CREDIT or DEBIT |
| Unexpected server error | `INTERNAL` | Internal server error |
| Server not running | (client side) | Cannot connect to the banking server ... |

Failed transfers and withdrawals caused by insufficient funds are still recorded in the
sender's history with status `FAILED`, as an audit trail.
