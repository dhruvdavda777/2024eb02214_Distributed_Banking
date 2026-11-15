# Question 1 - Protocol Buffers Banking Contract

**Student:** Dhruv Davda  
**BITS ID:** 2024eb02214  
**Email:** 2024eb02214@online.bits-pilani.ac.in

## Files

- `banking.proto`: AccountService and TransactionService definitions, request/response messages, and shared enums.
- `Q1_BitsDhruv.mp4`: Adapted walkthrough of the protocol definition.

The matching server is in `../2024eb02214_Q2_server_code/`; the client is in `../2024eb02214_Q3_submission/`.

## Generate Python stubs

Install the dependencies from the server or client folder, then run:

```sh
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. banking.proto
```

## Recording provenance

The video is a personalized copy of the supplied screen recording. A student-details strip has been added below the original screen content. The audio track has been completely removed; the video is silent. This is an adapted recording, not a new recording or a new claim of execution.
