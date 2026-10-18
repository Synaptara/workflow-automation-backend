import asyncio
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from .channels_auth import get_user_from_ticket
from .models import Credential, UserProfile, Workflow
from .serializers import WorkflowSerializer
from .utils import get_decrypted_token


class SecurityFixesTestCase(APITransactionTestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="StrongPassword123!",
        )
        self.profile = UserProfile.objects.get_or_create(
            user=self.user, defaults={"auth_provider": "credentials"}
        )[0]

    def test_c04_webhook_secret_not_exposed_in_serializer(self):
        """C-04: Ensure webhook_secret is NEVER serialized in WorkflowSerializer output."""
        wf = Workflow.objects.create(
            owner=self.user,
            name="My Secure Workflow",
            webhook_secret="super-sensitive-secret-value-12345",
        )
        serializer = WorkflowSerializer(wf)
        self.assertNotIn("webhook_secret", serializer.data)
        self.assertIn("webhook_url", serializer.data)
        self.assertIn("id", serializer.data)
        self.assertIn("name", serializer.data)

    def test_h03_websocket_ticket_flow(self):
        """H-03: Ensure WebSocket ticket generation is authenticated and single-use."""
        # Unauthenticated request should fail
        res_unauth = self.client.post("/api/auth/ws-ticket/")
        self.assertEqual(res_unauth.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request returns a short-lived ticket
        self.client.force_authenticate(user=self.user)
        res_auth = self.client.post("/api/auth/ws-ticket/")
        self.assertEqual(res_auth.status_code, status.HTTP_200_OK)
        ticket = res_auth.data.get("ticket")
        self.assertTrue(bool(ticket))

        # First consumption resolves to the user
        resolved_user = asyncio.run(get_user_from_ticket(ticket))
        self.assertEqual(resolved_user, self.user)

        # Second consumption fails (single-use token)
        replayed_user = asyncio.run(get_user_from_ticket(ticket))
        self.assertIsInstance(replayed_user, AnonymousUser)

        # Test JWTAuthMiddleware scope execution with ticket
        from .channels_auth import JWTAuthMiddleware
        res_ticket = self.client.post("/api/auth/ws-ticket/")
        new_ticket = res_ticket.data.get("ticket")

        async def dummy_app(s, r, send):
            return s

        middleware = JWTAuthMiddleware(dummy_app)
        scope = {"query_string": f"ticket={new_ticket}".encode("utf-8")}
        asyncio.run(middleware(scope, None, None))
        self.assertEqual(scope["user"], self.user)

    def test_h04_no_plaintext_credential_caching(self):
        """H-04: Ensure decrypted credentials are NOT cached unencrypted in Redis."""
        service_name = "github"
        secret_payload = {"access_token": "gho_super_secret_token_12345"}

        Credential.objects.create(
            owner=self.user,
            service=service_name,
            data=secret_payload,
        )

        # Cache is clear initially
        self.assertIsNone(cache.get(f"token_{service_name}_{self.user.id}"))

        # Fetch decrypted token
        data = get_decrypted_token(self.user.id, service_name)
        self.assertEqual(data, secret_payload)

        # Verify plaintext token is NOT cached in Redis
        self.assertIsNone(
            cache.get(f"token_{service_name}_{self.user.id}"),
            "Decrypted token MUST NOT be stored in Redis cache!",
        )

    def test_h06_social_auth_account_security(self):
        """H-06: Ensure social auth accounts have auth_provider set and cannot be accessed via password login."""
        social_user = User.objects.create_user(
            username="socialuser",
            email="socialuser@example.com",
        )
        social_user.set_unusable_password()
        social_user.save()

        UserProfile.objects.update_or_create(
            user=social_user, defaults={"auth_provider": "google"}
        )

        # Attempt password login for the social user
        login_res = self.client.post(
            "/api/auth/login/",
            {"username": "socialuser", "password": "AnyPasswordAttempt123!"},
        )
        self.assertEqual(login_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Google", login_res.data.get("detail", ""))

        # Verify standard user can still log in with credentials
        std_login_res = self.client.post(
            "/api/auth/login/",
            {"username": "testuser", "password": "StrongPassword123!"},
        )
        self.assertEqual(std_login_res.status_code, status.HTTP_200_OK)
        self.assertIn("access", std_login_res.data)
