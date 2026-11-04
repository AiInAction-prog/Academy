import unittest
from types import SimpleNamespace

from bot.broker import TopstepXClient
from bot.practice_guard import (
    PracticeAccountError,
    is_practice_account,
    require_practice_account,
)

PRACTICE = {"id": 1, "name": "PRAC-V2-123456-789", "canTrade": True}
COMBINE = {"id": 2, "name": "50KTC-V2-123456-789", "canTrade": True, "simulated": True}
FUNDED = {"id": 3, "name": "XFA-123456", "canTrade": True}


def make_client(accounts):
    settings = SimpleNamespace(base_url="https://example.invalid")
    client = TopstepXClient(settings)
    client.list_accounts = lambda only_active=True: accounts
    client._post = lambda path, payload: (_ for _ in ()).throw(
        AssertionError(f"no request should be sent, got {path}")
    )
    return client


class PracticeGuardTests(unittest.TestCase):
    def test_only_prac_names_count(self):
        self.assertTrue(is_practice_account(PRACTICE))
        self.assertFalse(is_practice_account(COMBINE))
        self.assertFalse(is_practice_account(FUNDED))
        self.assertFalse(is_practice_account({"id": 4}))

    def test_require_accepts_practice(self):
        self.assertEqual(require_practice_account([COMBINE, PRACTICE], 1), PRACTICE)

    def test_require_refuses_combine_and_funded(self):
        for account in (COMBINE, FUNDED):
            with self.assertRaises(PracticeAccountError):
                require_practice_account([PRACTICE, account], account["id"])

    def test_require_refuses_unknown_account(self):
        with self.assertRaises(PracticeAccountError):
            require_practice_account([PRACTICE], 99)

    def test_require_refuses_practice_that_cannot_trade(self):
        with self.assertRaises(PracticeAccountError):
            require_practice_account([dict(PRACTICE, canTrade=False)], 1)


class BrokerOrderBoundaryTests(unittest.TestCase):
    def test_unverified_account_cannot_place_or_close(self):
        client = make_client([PRACTICE, COMBINE])
        with self.assertRaises(PracticeAccountError):
            client.place_order(2, "CON.F.US.MNQ", "BUY", 1)
        with self.assertRaises(PracticeAccountError):
            client.close_position(2, "CON.F.US.MNQ")
        with self.assertRaises(PracticeAccountError):
            client.place_order(1, "CON.F.US.MNQ", "BUY", 1)

    def test_verifying_a_combine_account_fails(self):
        client = make_client([PRACTICE, COMBINE])
        with self.assertRaises(PracticeAccountError):
            client.verify_practice_account(2)
        with self.assertRaises(PracticeAccountError):
            client.place_order(2, "CON.F.US.MNQ", "BUY", 1)

    def test_verified_practice_account_reaches_the_api(self):
        client = make_client([PRACTICE])
        client.verify_practice_account(1)
        sent = []
        client._post = lambda path, payload: sent.append((path, payload)) or {
            "success": True,
            "orderId": 7,
        }
        client.settings.instrument = SimpleNamespace(tick_size=0.25)
        result = client.place_order(1, "CON.F.US.MNQ", "BUY", 1)
        self.assertEqual(result.status, "placed")
        self.assertEqual(sent[0][0], "/api/Order/place")
        self.assertEqual(sent[0][1]["accountId"], 1)


if __name__ == "__main__":
    unittest.main()
