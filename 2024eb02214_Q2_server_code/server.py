"""
Personalized submission copy for Dhruv Davda (2024eb02214).
Email: 2024eb02214@online.bits-pilani.ac.in

server.py - gRPC server for the distributed banking system.

It hosts two gRPC services defined in banking.proto on one port:
  * AccountService     - GetBalance, UpdateBalance
  * TransactionService - InitiateTransfer, GetTransactionHistory

Both services share one in-memory BankStore, so a transfer made through the
TransactionService is immediately visible through the AccountService.

Error handling - every problem is returned to the client as a gRPC status code:
  INVALID_ARGUMENT    invalid data (empty user id, amount <= 0, same account, ...)
  NOT_FOUND           the user / account does not exist
  FAILED_PRECONDITION insufficient funds
  INTERNAL            any unexpected server error

Run:
    python server.py                # listens on port 50051
    python server.py --port 6000
"""

import argparse
import functools
import logging
import math
import threading
from concurrent import futures
from datetime import datetime, timezone
from decimal import Decimal

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

import banking_pb2 as pb
import banking_pb2_grpc as pb_grpc

CURRENCY = "INR"
MAX_AMOUNT = Decimal("1000000.00")   # largest amount allowed in one operation
CENT = Decimal("0.01")

log = logging.getLogger("bank-server")


# ---------------------------------------------------------------------------
# Errors and input validation
# ---------------------------------------------------------------------------
class BankError(Exception):
    """A business error that is sent back to the client as a gRPC status."""

    def __init__(self, code: grpc.StatusCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_user_id(user_id: str, field: str = "user_id") -> str:
    """User ids must be non-empty. Surrounding spaces are removed."""
    user_id = (user_id or "").strip()
    if not user_id:
        raise BankError(grpc.StatusCode.INVALID_ARGUMENT, f"{field} is required")
    return user_id


def validate_amount(amount: float) -> Decimal:
    """Amounts must be a real number > 0, have at most 2 decimal places and be
    at most MAX_AMOUNT. They are converted to Decimal so money is exact
    (floats cannot store values like 0.1 exactly)."""
    if amount is None or not math.isfinite(amount):
        raise BankError(grpc.StatusCode.INVALID_ARGUMENT, "Amount must be a valid number")
    if amount <= 0:
        raise BankError(grpc.StatusCode.INVALID_ARGUMENT,
                        f"Amount must be greater than 0 (got {amount})")
    value = Decimal(str(amount))
    if value != value.quantize(CENT):
        raise BankError(grpc.StatusCode.INVALID_ARGUMENT,
                        f"Amount can have at most 2 decimal places (got {amount})")
    if value > MAX_AMOUNT:
        raise BankError(grpc.StatusCode.INVALID_ARGUMENT,
                        f"Amount cannot exceed {MAX_AMOUNT} per operation")
    return value.quantize(CENT)


def now_timestamp() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.now(timezone.utc))
    return ts


# ---------------------------------------------------------------------------
# In-memory data store shared by both services
# ---------------------------------------------------------------------------
class BankStore:
    """Holds all accounts and transactions in memory.

    gRPC serves requests on several threads at once, so every read/write of
    the shared data happens while holding self._lock. This prevents race
    conditions such as two transfers spending the same money twice.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._accounts = {}        # user_id -> {"name": str, "balance": Decimal}
        self._transactions = []    # list of pb.Transaction, oldest first
        self._next_txn = 1

    # ---- helpers (call only while holding the lock) -----------------------
    def _account(self, user_id: str) -> dict:
        account = self._accounts.get(user_id)
        if account is None:
            raise BankError(grpc.StatusCode.NOT_FOUND, f"User '{user_id}' does not exist")
        return account

    def _new_txn_id(self) -> str:
        txn_id = f"TXN{self._next_txn:06d}"
        self._next_txn += 1
        return txn_id

    def _record(self, **fields) -> pb.Transaction:
        txn = pb.Transaction(transaction_id=self._new_txn_id(),
                             timestamp=now_timestamp(), **fields)
        self._transactions.append(txn)
        return txn

    @staticmethod
    def _apply_update(account: dict, amount: Decimal, update_type: int) -> None:
        """Core balance-update rule, used by both UpdateBalance and transfers."""
        if update_type == pb.CREDIT:
            account["balance"] += amount
        elif update_type == pb.DEBIT:
            if account["balance"] < amount:
                raise BankError(grpc.StatusCode.FAILED_PRECONDITION,
                                f"Insufficient funds: balance is {account['balance']} "
                                f"{CURRENCY}, requested {amount} {CURRENCY}")
            account["balance"] -= amount
        else:
            raise BankError(grpc.StatusCode.INVALID_ARGUMENT,
                            "Update type must be CREDIT or DEBIT")

    # ---- public operations ------------------------------------------------
    def open_account(self, user_id: str, name: str, balance: str) -> None:
        with self._lock:
            self._accounts[user_id] = {"name": name, "balance": Decimal(balance)}

    def get_balance(self, user_id: str):
        with self._lock:
            account = self._account(user_id)
            return account["name"], account["balance"]

    def update_balance(self, user_id: str, amount: Decimal, update_type: int, description: str):
        with self._lock:
            account = self._account(user_id)
            txn_type = pb.DEPOSIT if update_type == pb.CREDIT else pb.WITHDRAWAL
            try:
                self._apply_update(account, amount, update_type)
            except BankError as err:
                if err.code == grpc.StatusCode.FAILED_PRECONDITION:   # keep an audit trail
                    self._record(type=txn_type, status=pb.FAILED, amount=float(amount),
                                 from_user_id=user_id, description=description,
                                 failure_reason=err.message)
                raise
            txn = self._record(
                type=txn_type, status=pb.SUCCESS, amount=float(amount),
                to_user_id=user_id if update_type == pb.CREDIT else "",
                from_user_id=user_id if update_type == pb.DEBIT else "",
                description=description)
            return account["name"], account["balance"], txn

    def transfer(self, from_id: str, to_id: str, amount: Decimal, description: str):
        if from_id == to_id:
            raise BankError(grpc.StatusCode.INVALID_ARGUMENT,
                            "Cannot transfer to the same account")
        with self._lock:
            # Look up BOTH accounts before changing anything, so an unknown
            # user never leaves a half-finished transfer behind.
            sender = self._account(from_id)
            receiver = self._account(to_id)
            try:
                self._apply_update(sender, amount, pb.DEBIT)
            except BankError as err:
                self._record(type=pb.TRANSFER, status=pb.FAILED, from_user_id=from_id,
                             to_user_id=to_id, amount=float(amount),
                             description=description, failure_reason=err.message)
                raise
            self._apply_update(receiver, amount, pb.CREDIT)
            # Debit and credit happen under the same lock -> the transfer is atomic.
            txn = self._record(type=pb.TRANSFER, status=pb.SUCCESS, from_user_id=from_id,
                               to_user_id=to_id, amount=float(amount),
                               description=description)
            return txn, sender["balance"]

    def history(self, user_id: str, limit: int):
        if limit < 0:
            raise BankError(grpc.StatusCode.INVALID_ARGUMENT, "limit cannot be negative")
        with self._lock:
            self._account(user_id)                      # NOT_FOUND if unknown user
            # A user sees everything they sent plus everything they successfully
            # received. A failed transfer is shown only to the sender, because
            # no money ever reached the receiver.
            mine = [t for t in reversed(self._transactions)          # newest first
                    if t.from_user_id == user_id
                    or (t.to_user_id == user_id and t.status == pb.SUCCESS)]
            return (mine[:limit] if limit else mine), len(mine)


# ---------------------------------------------------------------------------
# Turn BankError / unexpected exceptions into gRPC status codes
# ---------------------------------------------------------------------------
def handle_errors(rpc_method):
    @functools.wraps(rpc_method)
    def wrapper(self, request, context):
        name = rpc_method.__name__
        try:
            return rpc_method(self, request, context)
        except BankError as err:
            log.warning("%s -> %s: %s", name, err.code.name, err.message)
            context.abort(err.code, err.message)
        except Exception:                                # bug or unexpected problem
            log.exception("%s -> INTERNAL error", name)
            context.abort(grpc.StatusCode.INTERNAL, "Internal server error")
    return wrapper


# ---------------------------------------------------------------------------
# Service implementations
# ---------------------------------------------------------------------------
class AccountService(pb_grpc.AccountServiceServicer):
    """Account Management Service: getBalance and updateBalance."""

    def __init__(self, store: BankStore):
        self.store = store

    @handle_errors
    def GetBalance(self, request, context):
        user_id = validate_user_id(request.user_id)
        name, balance = self.store.get_balance(user_id)
        log.info("GetBalance user=%s -> %s %s", user_id, balance, CURRENCY)
        return pb.BalanceResponse(user_id=user_id, account_holder=name,
                                  balance=float(balance), currency=CURRENCY,
                                  message="Balance retrieved successfully")

    @handle_errors
    def UpdateBalance(self, request, context):
        user_id = validate_user_id(request.user_id)
        if request.type not in (pb.CREDIT, pb.DEBIT):
            raise BankError(grpc.StatusCode.INVALID_ARGUMENT,
                            "Update type must be CREDIT or DEBIT")
        amount = validate_amount(request.amount)
        name, balance, txn = self.store.update_balance(
            user_id, amount, request.type, request.description.strip())
        action = "credited to" if request.type == pb.CREDIT else "debited from"
        log.info("UpdateBalance %s user=%s amount=%s -> balance %s (%s)",
                 pb.UpdateType.Name(request.type), user_id, amount, balance, txn.transaction_id)
        return pb.BalanceResponse(user_id=user_id, account_holder=name,
                                  balance=float(balance), currency=CURRENCY,
                                  transaction_id=txn.transaction_id,
                                  message=f"{amount} {CURRENCY} {action} {user_id}")


class TransactionService(pb_grpc.TransactionServiceServicer):
    """Transaction Service: initiateTransfer and getTransactionHistory."""

    def __init__(self, store: BankStore):
        self.store = store

    @handle_errors
    def InitiateTransfer(self, request, context):
        from_id = validate_user_id(request.from_user_id, "from_user_id")
        to_id = validate_user_id(request.to_user_id, "to_user_id")
        amount = validate_amount(request.amount)
        txn, sender_balance = self.store.transfer(from_id, to_id, amount,
                                                  request.description.strip())
        log.info("InitiateTransfer %s -> %s amount=%s (%s)",
                 from_id, to_id, amount, txn.transaction_id)
        return pb.TransferResponse(
            transaction_id=txn.transaction_id, status=pb.SUCCESS,
            from_user_id=from_id, to_user_id=to_id, amount=float(amount),
            from_balance_after=float(sender_balance), timestamp=txn.timestamp,
            message=f"Transferred {amount} {CURRENCY} from {from_id} to {to_id}")

    @handle_errors
    def GetTransactionHistory(self, request, context):
        user_id = validate_user_id(request.user_id)
        transactions, total = self.store.history(user_id, request.limit)
        log.info("GetTransactionHistory user=%s -> %d of %d transaction(s)",
                 user_id, len(transactions), total)
        return pb.TransactionHistoryResponse(user_id=user_id,
                                             transactions=transactions,
                                             total_count=total)


# ---------------------------------------------------------------------------
# Server start-up
# ---------------------------------------------------------------------------
def create_store() -> BankStore:
    """Sample accounts so the system can be tested straight away."""
    store = BankStore()
    store.open_account("U1001", "Aarav Sharma", "5000.00")
    store.open_account("U1002", "Diya Verma", "3000.00")
    store.open_account("U1003", "Kabir Iyer", "500.00")
    return store


def serve(port: int) -> None:
    store = create_store()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_AccountServiceServicer_to_server(AccountService(store), server)
    pb_grpc.add_TransactionServiceServicer_to_server(TransactionService(store), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()

    log.info("Banking gRPC server started on port %d", port)
    log.info("Services: AccountService (GetBalance, UpdateBalance), "
             "TransactionService (InitiateTransfer, GetTransactionHistory)")
    for user_id in ("U1001", "U1002", "U1003"):
        name, balance = store.get_balance(user_id)
        log.info("  account %s  %-13s %10s %s", user_id, name, balance, CURRENCY)
    log.info("Press Ctrl+C to stop")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.stop(grace=2).wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Banking gRPC server")
    parser.add_argument("--port", type=int, default=50051, help="port to listen on")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    serve(args.port)
