"""AWS integrations for DoorLedger, all optional and behind env flags.

* ``dynamo``          mirrors every ledger record to DynamoDB (``DOORLEDGER_DYNAMO=1``).
* ``snapshot``        read-only, JSON-serialisable copy of one household's state, used to run
                      the CareAgent somewhere else (AgentCore Runtime) without giving it the
                      live engine, the notifier, or any phone numbers.
* ``agentcore``       client for a CareAgent deployed to Amazon Bedrock AgentCore Runtime
                      (``DOORLEDGER_AGENTCORE_ARN``).

Importing this package must stay cheap: no boto3 client is created at import time.
"""
