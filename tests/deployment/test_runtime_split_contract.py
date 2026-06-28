"""Tests for deployment runtime ownership split contract.

These tests verify app-repo-side contract expectations after the runtime
deployment ownership is moved to the `fk-cesis` infrastructure repository.

All tests use plain pathlib reads + string assertions. No pytest-django
database requirement. Tests MUST fail against the current repo state and
pass after the planned changes in:
  docs/superpowers/plans/2026-06-27-deployment-runtime-split.md
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_all(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_head(path: Path, lines: int) -> str:
    """Read the first *lines* lines of a file."""
    with path.open(encoding="utf-8") as fh:
        return "".join(fh.readline() for _ in range(lines))


# ---------------------------------------------------------------------------
# compose.yaml — header contract
# ---------------------------------------------------------------------------

class TestComposeYamlHeader:
    """compose.yaml must be local smoke, not production source-of-truth."""

    @property
    def content(self) -> str:
        return _read_all(REPO_ROOT / "compose.yaml")

    @property
    def header(self) -> str:
        return _read_head(REPO_ROOT / "compose.yaml", 10)

    def test_header_is_local_smoke_not_production(self):
        """Header must describe local smoke, not production/host deploy."""
        assert "local" in self.header.lower(), (
            "compose.yaml header must mention 'local'"
        )
        assert "production compose" not in self.header.lower(), (
            "compose.yaml must NOT describe itself as 'production compose stack'"
        )

    def test_header_references_fk_cesis_ownership(self):
        """Header must reference fk-cesis as runtime owner."""
        header = self.header.lower()
        # Must mention fk-cesis as a distinct repo name, not just nested
        # inside the app name "fk-cesis-mms".
        assert "github.com/linards-kalvans/fk-cesis" in header, (
            "compose.yaml header must reference the fk-cesis infra repo URL"
        )

    def test_header_warns_not_production_source_of_truth(self):
        """Header must warn this is not production source-of-truth."""
        assert "source-of-truth" in self.header.lower() or "source of truth" in self.header.lower(), (
            "compose.yaml header must mark itself as NOT the production source-of-truth"
        )


# ---------------------------------------------------------------------------
# docs/deployment.md — ownership pointer, not full runbook
# ---------------------------------------------------------------------------

class TestDeploymentDocIsPointer:
    """docs/deployment.md must be a short ownership pointer, not a full runbook."""

    @property
    def content(self) -> str:
        return _read_all(REPO_ROOT / "docs" / "deployment.md")

    def test_points_to_fk_cesis(self):
        """Must state that fk-cesis owns deployed runtime."""
        content_lower = self.content.lower()
        # Must reference the fk-cesis infra repo as a distinct entity,
        # not just as part of the app name "fk-cesis-mms".
        assert "github.com/linards-kalvans/fk-cesis" in content_lower, (
            "docs/deployment.md must reference the fk-cesis infra repo URL"
        )

    def test_points_to_runtime_contract(self):
        """Must link to docs/runtime-contract.md."""
        assert "runtime-contract.md" in self.content, (
            "docs/deployment.md must point to docs/runtime-contract.md"
        )

    def test_points_to_local_smoke_docs(self):
        """Must link to docs/local-docker-smoke.md."""
        assert "local-docker-smoke.md" in self.content, (
            "docs/deployment.md must point to docs/local-docker-smoke.md"
        )

    def test_no_embedded_listener_script(self):
        """Must NOT contain an embedded deploy listener Python script."""
        assert "#!/usr/bin/env python3" not in self.content, (
            "docs/deployment.md must NOT embed the deploy listener script"
        )
        assert "DEPLOY_CMD" not in self.content, (
            "docs/deployment.md must NOT embed deploy listener source code"
        )

    def test_no_embedded_systemd_unit(self):
        """Must NOT contain an embedded systemd unit definition."""
        assert "[Unit]" not in self.content, (
            "docs/deployment.md must NOT embed a systemd unit"
        )

    def test_no_embedded_caddyfile_patch(self):
        """Must NOT contain an embedded Caddyfile patch."""
        assert "Caddyfile" not in self.content, (
            "docs/deployment.md must NOT embed a Caddyfile patch"
        )

    def test_no_host_provisioning_runbook(self):
        """Must NOT contain a host provisioning runbook with apt-get / useradd."""
        assert "useradd" not in self.content, (
            "docs/deployment.md must NOT contain host provisioning commands (useradd)"
        )
        assert "apt-get" not in self.content, (
            "docs/deployment.md must NOT contain host provisioning commands (apt-get)"
        )

    def test_short_not_full_runbook(self):
        """Should be short ownership pointer, not 400+ line runbook."""
        line_count = len(self.content.splitlines())
        assert line_count < 80, (
            f"docs/deployment.md must be a short pointer (<80 lines), "
            f"got {line_count}"
        )


# ---------------------------------------------------------------------------
# docs/runtime-contract.md — existence + contract anchors
# ---------------------------------------------------------------------------

class TestRuntimeContractDoc:
    """docs/runtime-contract.md must exist and contain required contract anchors."""

    @property
    def exists(self) -> bool:
        return (REPO_ROOT / "docs" / "runtime-contract.md").is_file()

    def test_file_exists(self):
        """docs/runtime-contract.md must exist."""
        assert self.exists, (
            "docs/runtime-contract.md must exist in the app repo"
        )

    # ---- optional convenience helper ----
    def _content(self) -> str:
        return _read_all(REPO_ROOT / "docs" / "runtime-contract.md")

    def test_registry_image_anchor(self):
        """Must document the registry image name."""
        content = self._content()
        assert "codeberg.org" in content, (
            "runtime-contract.md must mention the Codeberg registry image"
        )
        assert "fk-cesis-mms" in content, (
            "runtime-contract.md must name the fk-cesis-mms image"
        )

    def test_tag_model_anchors(self):
        """Must document dev, main, and X.Y immutable tag model."""
        content = self._content()
        # dev floating tag
        assert "`dev`" in content or ":dev" in content, (
            "runtime-contract.md must document the dev floating tag"
        )
        # main floating tag
        assert "`main`" in content or ":main" in content, (
            "runtime-contract.md must document the main floating tag"
        )
        # immutable major.minor
        assert "major" in content.lower() and "minor" in content.lower(), (
            "runtime-contract.md must document immutable X.Y tags"
        )

    def test_web_and_qcluster_services(self):
        """Must document web and qcluster as the two runtime services."""
        content = self._content()
        assert "web" in content.lower(), (
            "runtime-contract.md must document the web service"
        )
        assert "qcluster" in content.lower(), (
            "runtime-contract.md must document the qcluster service"
        )

    def test_healthcheck_endpoint(self):
        """Must document the /healthz endpoint."""
        content = self._content()
        assert "/healthz" in content, (
            "runtime-contract.md must document the /healthz healthcheck endpoint"
        )

    def test_database_url_env_var(self):
        """Must document DATABASE_URL requirement."""
        content = self._content()
        assert "DATABASE_URL" in content, (
            "runtime-contract.md must document DATABASE_URL as required"
        )

    def test_uploads_and_private_uploads_paths(self):
        """Must document uploads and private-uploads mounted paths."""
        content = self._content()
        assert "uploads" in content, (
            "runtime-contract.md must document uploads volume"
        )
        assert "private-uploads" in content, (
            "runtime-contract.md must document private-uploads volume"
        )

    def test_rollback_image_tag_pin(self):
        """Must document IMAGE_TAG pin for rollback."""
        content = self._content()
        assert "IMAGE_TAG" in content, (
            "runtime-contract.md must document IMAGE_TAG for rollback"
        )

    def test_ownership_section(self):
        """Must state that fk-cesis-mms builds images, fk-cesis owns runtime."""
        content = self._content()
        assert "fk-cesis" in content.lower(), (
            "runtime-contract.md must mention fk-cesis ownership boundary"
        )


# ---------------------------------------------------------------------------
# docs/local-docker-smoke.md — existence + local-smoke-only stance
# ---------------------------------------------------------------------------

class TestLocalDockerSmokeDoc:
    """docs/local-docker-smoke.md must exist and state local-only use."""

    @property
    def exists(self) -> bool:
        return (REPO_ROOT / "docs" / "local-docker-smoke.md").is_file()

    def test_file_exists(self):
        """docs/local-docker-smoke.md must exist."""
        assert self.exists, (
            "docs/local-docker-smoke.md must exist in the app repo"
        )

    def test_local_only_stance(self):
        """Must state this is local smoke, not production runtime source-of-truth."""
        content = _read_all(REPO_ROOT / "docs" / "local-docker-smoke.md")
        assert "local" in content.lower(), (
            "local-docker-smoke.md must describe itself as local"
        )

    def test_not_production_source_of_truth(self):
        """Must explicitly state it is NOT production source-of-truth."""
        content = _read_all(REPO_ROOT / "docs" / "local-docker-smoke.md")
        phrase_found = (
            "not production" in content.lower()
            or "not the production" in content.lower()
        )
        assert phrase_found, (
            "local-docker-smoke.md must warn it is not production source-of-truth"
        )

    def test_references_fk_cesis(self):
        """Must reference fk-cesis for deployed runtime configuration."""
        content = _read_all(REPO_ROOT / "docs" / "local-docker-smoke.md")
        assert "fk-cesis" in content.lower(), (
            "local-docker-smoke.md must point to fk-cesis for deployed runtime"
        )


# ---------------------------------------------------------------------------
# .woodpecker.yml — CI comments describe webhook as optional handoff
# ---------------------------------------------------------------------------

class TestWoodpeckerCIComments:
    """.woodpecker.yml must describe deploy notification as optional infra handoff."""

    @property
    def content(self) -> str:
        return _read_all(REPO_ROOT / ".woodpecker.yml")

    @property
    def top_comments(self) -> str:
        return _read_head(REPO_ROOT / ".woodpecker.yml", 15)

    @property
    def secrets_block(self) -> str:
        """Roughly lines 20-45 of the file."""
        lines = self.content.splitlines()
        return "\n".join(lines[19:min(50, len(lines))])

    def test_top_comments_describe_webhook_as_optional_handoff(self):
        """The top comments must not describe deploy as CI-owned push; must be optional handoff."""
        # Must NOT say "notify dev server" / "notify prod server"
        assert "notify dev" not in self.top_comments.lower(), (
            ".woodpecker.yml top comments must NOT describe deploy as 'notify dev server'"
        )
        assert "notify prod" not in self.top_comments.lower(), (
            ".woodpecker.yml top comments must NOT describe deploy as 'notify prod server'"
        )
        # Should mention infra or fk-cesis or optional handoff
        has_ownership = (
            "fk-cesis" in self.top_comments.lower()
            or "infra" in self.top_comments.lower()
            or "optional" in self.top_comments.lower()
        )
        assert has_ownership, (
            ".woodpecker.yml top comments must reference fk-cesis/infra ownership "
            "or describe webhook as optional"
        )

    def test_secrets_block_describes_webhook_as_optional(self):
        """Secret descriptions must frame webhook secrets as optional/infra-owned."""
        secrets = self.secrets_block.lower()
        # Must NOT say "shared with the dev server's listener"
        assert "shared with the dev server" not in secrets, (
            ".woodpecker.yml secrets must NOT claim webhook secrets are "
            "'shared with the dev server's listener'"
        )
        # Should describe as optional or infra-owned
        assert "optional" in secrets or "fk-cesis" in secrets or "infra" in secrets, (
            ".woodpecker.yml secrets block must describe deploy webhook as optional "
            "or infra-owned"
        )

    def test_build_and_push_pipeline_preserved(self):
        """Build/publish pipeline must still be present (build-and-push, prepare-tags)."""
        assert "build-and-push" in self.content, (
            ".woodpecker.yml must still contain build-and-push step"
        )
        assert "prepare-tags" in self.content, (
            ".woodpecker.yml must still contain prepare-tags step — dev and main"
        )


# ---------------------------------------------------------------------------
# README.md — no longer a deployment runbook link
# ---------------------------------------------------------------------------

class TestReadmeLinks:
    """README.md must point to runtime contract / local smoke, not deployment runbook."""

    @property
    def content(self) -> str:
        return _read_all(REPO_ROOT / "README.md")

    def test_no_deployment_runbook_link(self):
        """README must NOT have a 'Deployment runbook: docs/deployment.md' link."""
        assert "Deployment runbook:" not in self.content, (
            "README.md must not link to docs/deployment.md as a deployment runbook"
        )

    def test_runtime_contract_mentioned(self):
        """README must mention runtime contract or local Docker smoke."""
        has_contract = "runtime-contract" in self.content.lower()
        has_smoke = "local-docker-smoke" in self.content.lower()
        assert has_contract or has_smoke, (
            "README.md must reference runtime-contract.md or local-docker-smoke.md"
        )

    def test_fk_cesis_ownership_mentioned(self):
        """README must mention that fk-cesis owns deployed runtime."""
        content_lower = self.content.lower()
        # Must reference the fk-cesis infra repo explicitly, not just
        # as part of "fk-cesis-mms".
        assert "github.com/linards-kalvans/fk-cesis" in content_lower, (
            "README.md must reference the fk-cesis infra repo URL"
        )
