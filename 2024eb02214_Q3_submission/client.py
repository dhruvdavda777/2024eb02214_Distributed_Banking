"""
Personalized submission copy for Dhruv Davda (2024eb02214).
Email: 2024eb02214@online.bits-pilani.ac.in

client.py - gRPC client for the distributed banking system.

It talks to the server over the network using the stubs generated from
banking.proto (AccountServiceStub and TransactionServiceStub).

Usage (start server.py first):
    python client.py balance  U1001
    python client.py deposit  U1001 1000  --note "Salary"
    python client.py withdraw U1002 200   --note "ATM"
    python client.py transfer U1001 U1002 1500 --note "Rent"
    python client.py history  U1001 [--limit 5]
    python client.py demo                  # full test incl. error handling

Add  --server HOST:PORT  to reach a server on another machine
(default: localhost:50051).
"""

import argparse
import sys

import grpc

import banking_pb2 as pb
import banking_pb2_grpc as pb_grpc

TIMEOUT_SECONDS = 5     # deadline for every RPC


class BankClient:
    """Thin wrapper around the two generated gRPC stubs."""

    def __init__(self, address: str):
        self.address = address
        self.channel = grpc.insecure_channel(address)
        self.accounts = pb_grpc.AccountServiceStub(self.channel)
        self.transactions = pb_grpc.TransactionServiceStub(self.channel)

    def wait_until_ready(self, seconds: float = 3) -> None:
        """Fail fast with a clear message if the server is not running."""
        try:
            grpc.channel_ready_future(self.channel).result(timeout=seconds)
        except grpc.FutureTimeoutError:
            sys.exit(f"Cannot connect to the banking server at {self.address}. "
                     "Is server.py running?")

    # ---- AccountService ---------------------------------------------------
    def get_balance(self, user_id):
        return self.accounts.GetBalance(
            pb.GetBalanceRequest(user_id=user_id), timeout=TIMEOUT_SECONDS)

    def update_balance(self, user_id, amount, update_type, description=""):
        return self.accounts.UpdateBalance(
            pb.UpdateBalanceRequest(user_id=user_id, amount=amount,
                                    type=update_type, description=description),
            timeout=TIMEOUT_SECONDS)

    # ---- TransactionService -----------------------------------------------
    def transfer(self, from_id, to_id, amount, description=""):
        return self.transactions.InitiateTransfer(
            pb.TransferRequest(from_user_id=from_id, to_user_id=to_id,
                               amount=amount, description=description),
            timeout=TIMEOUT_SECONDS)

    def history(self, user_id, limit=0):
        return self.transactions.GetTransactionHistory(
            pb.TransactionHistoryRequest(user_id=user_id, limit=limit),
            timeout=TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------
def money(value: float) -> str:
    return f"{value:,.2f}"


def print_balance(resp) -> None:
    print(f"  Account : {resp.user_id} ({resp.account_holder})")
    print(f"  Balance : {money(resp.balance)} {resp.currency}")
    if resp.transaction_id:
        print(f"  Txn ID  : {resp.transaction_id}")
    print(f"  Result  : {resp.message}")


def print_transfer(resp) -> None:
    when = resp.timestamp.ToDatetime().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"  Txn ID  : {resp.transaction_id}  [{pb.TransactionStatus.Name(resp.status)}]")
    print(f"  From/To : {resp.from_user_id} -> {resp.to_user_id}")
    print(f"  Amount  : {money(resp.amount)}")
    print(f"  Sender balance after: {money(resp.from_balance_after)}")
    print(f"  Time    : {when}")
    print(f"  Result  : {resp.message}")


def print_history(resp) -> None:
    print(f"  Transactions for {resp.user_id}: showing {len(resp.transactions)} "
          f"of {resp.total_count} (newest first)")
    if not resp.transactions:
        print("  (no transactions yet)")
        return
    print(f"  {'Txn ID':<10} {'Time (UTC)':<19} {'Type':<10} {'Status':<7} "
          f"{'From':<6} {'To':<6} {'Amount':>11}  Note")
    print("  " + "-" * 92)
    for t in resp.transactions:
        when = t.timestamp.ToDatetime().strftime("%Y-%m-%d %H:%M:%S")
        # money leaving this user's account is shown as negative; failed
        # transactions moved no money, so they get no sign
        if t.status == pb.FAILED:
            sign = " "
        else:
            sign = "-" if t.from_user_id == resp.user_id else "+"
        note = t.description or ""
        if t.status == pb.FAILED:
            note = f"{note} | {t.failure_reason}".strip(" |")
        print(f"  {t.transaction_id:<10} {when:<19} "
              f"{pb.TransactionType.Name(t.type):<10} {pb.TransactionStatus.Name(t.status):<7} "
              f"{t.from_user_id or '-':<6} {t.to_user_id or '-':<6} "
              f"{sign}{money(t.amount):>10}  {note}")


def call(description: str, rpc, printer=None) -> bool:
    """Run one RPC, print its result, and turn gRPC errors into readable
    messages instead of a crash. Returns True on success."""
    print(f"\n>>> {description}")
    try:
        resp = rpc()
    except grpc.RpcError as err:
        print(f"  ERROR [{err.code().name}]: {err.details()}")
        return False
    if printer:
        printer(resp)
    return True


# ---------------------------------------------------------------------------
# Demo: tests every RPC and every error case
# ---------------------------------------------------------------------------
PAUSE = False   # set by "demo --pause": wait for Enter before each section


def heading(text: str) -> None:
    if PAUSE:
        input("\n[Press Enter for the next step] ")
    print("\n" + "=" * 70 + f"\n{text}\n" + "=" * 70)


def run_demo(bank: BankClient) -> None:
    heading("1. getBalance - check starting balances")
    for user in ("U1001", "U1002", "U1003"):
        call(f"GetBalance({user})", lambda u=user: bank.get_balance(u), print_balance)

    heading("2. updateBalance - credit (deposit) and debit (withdrawal)")
    call("UpdateBalance(U1001, CREDIT 1000.00, 'Salary')",
         lambda: bank.update_balance("U1001", 1000.00, pb.CREDIT, "Salary"), print_balance)
    call("UpdateBalance(U1002, DEBIT 200.00, 'ATM withdrawal')",
         lambda: bank.update_balance("U1002", 200.00, pb.DEBIT, "ATM withdrawal"), print_balance)

    heading("3. initiateTransfer - move money between accounts")
    call("InitiateTransfer(U1001 -> U1002, 1500.00, 'Rent')",
         lambda: bank.transfer("U1001", "U1002", 1500.00, "Rent"), print_transfer)
    call("InitiateTransfer(U1002 -> U1003, 250.50, 'Dinner')",
         lambda: bank.transfer("U1002", "U1003", 250.50, "Dinner"), print_transfer)

    heading("4. getBalance - balances after the transfers")
    for user in ("U1001", "U1002", "U1003"):
        call(f"GetBalance({user})", lambda u=user: bank.get_balance(u), print_balance)

    heading("5. Error handling")
    call("Insufficient funds: InitiateTransfer(U1003 -> U1001, 10000.00)",
         lambda: bank.transfer("U1003", "U1001", 10000.00, "Too much"))
    call("Insufficient funds: UpdateBalance(U1003, DEBIT 5000.00)",
         lambda: bank.update_balance("U1003", 5000.00, pb.DEBIT, "Large withdrawal"))
    call("Non-existing user: GetBalance(U9999)",
         lambda: bank.get_balance("U9999"))
    call("Non-existing user: InitiateTransfer(U1001 -> U9999, 100.00)",
         lambda: bank.transfer("U1001", "U9999", 100.00))
    call("Invalid data: negative amount InitiateTransfer(U1001 -> U1002, -50.00)",
         lambda: bank.transfer("U1001", "U1002", -50.00))
    call("Invalid data: zero amount UpdateBalance(U1001, CREDIT 0)",
         lambda: bank.update_balance("U1001", 0, pb.CREDIT))
    call("Invalid data: 3 decimal places InitiateTransfer(U1001 -> U1002, 10.555)",
         lambda: bank.transfer("U1001", "U1002", 10.555))
    call("Invalid data: same account InitiateTransfer(U1001 -> U1001, 100.00)",
         lambda: bank.transfer("U1001", "U1001", 100.00))
    call("Invalid data: empty user id GetBalance('')",
         lambda: bank.get_balance(""))
    call("Invalid data: missing CREDIT/DEBIT type in UpdateBalance",
         lambda: bank.update_balance("U1001", 100.00, pb.UPDATE_TYPE_UNSPECIFIED))

    heading("6. Balances unchanged by the failed requests")
    for user in ("U1001", "U1002", "U1003"):
        call(f"GetBalance({user})", lambda u=user: bank.get_balance(u), print_balance)

    heading("7. getTransactionHistory")
    for user in ("U1001", "U1002", "U1003"):
        call(f"GetTransactionHistory({user})", lambda u=user: bank.history(u), print_history)
    call("GetTransactionHistory(U1003, limit=2)",
         lambda: bank.history("U1003", 2), print_history)
    call("Non-existing user: GetTransactionHistory(U9999)",
         lambda: bank.history("U9999"))

    print("\nDemo finished.")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Banking gRPC client")
    parser.add_argument("--server", default="localhost:50051",
                        help="server address HOST:PORT (default localhost:50051)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("balance", help="get the balance of an account")
    p.add_argument("user_id")

    for name, help_text in (("deposit", "credit an account (updateBalance CREDIT)"),
                            ("withdraw", "debit an account (updateBalance DEBIT)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("user_id")
        p.add_argument("amount", type=float)
        p.add_argument("--note", default="")

    p = sub.add_parser("transfer", help="transfer money between accounts")
    p.add_argument("from_user_id")
    p.add_argument("to_user_id")
    p.add_argument("amount", type=float)
    p.add_argument("--note", default="")

    p = sub.add_parser("history", help="show the transaction history of an account")
    p.add_argument("user_id")
    p.add_argument("--limit", type=int, default=0, help="max transactions (0 = all)")

    p = sub.add_parser("demo", help="run the full test scenario")
    p.add_argument("--pause", action="store_true",
                   help="wait for Enter before each section (for live demos)")

    args = parser.parse_args()
    bank = BankClient(args.server)
    bank.wait_until_ready()
    print(f"Connected to banking server at {args.server}")

    if args.command == "balance":
        ok = call(f"GetBalance({args.user_id})",
                  lambda: bank.get_balance(args.user_id), print_balance)
    elif args.command in ("deposit", "withdraw"):
        kind = pb.CREDIT if args.command == "deposit" else pb.DEBIT
        ok = call(f"UpdateBalance({args.user_id}, {pb.UpdateType.Name(kind)} {args.amount})",
                  lambda: bank.update_balance(args.user_id, args.amount, kind, args.note),
                  print_balance)
    elif args.command == "transfer":
        ok = call(f"InitiateTransfer({args.from_user_id} -> {args.to_user_id}, {args.amount})",
                  lambda: bank.transfer(args.from_user_id, args.to_user_id,
                                        args.amount, args.note),
                  print_transfer)
    elif args.command == "history":
        ok = call(f"GetTransactionHistory({args.user_id})",
                  lambda: bank.history(args.user_id, args.limit), print_history)
    else:
        global PAUSE
        PAUSE = args.pause
        run_demo(bank)
        ok = True
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
