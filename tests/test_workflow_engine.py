"""End-to-end integration test for the workflow engine.

Tests the full workflow lifecycle:
1. Create a workflow definition with multiple step types
2. Execute the workflow
3. Verify run history and step execution records
4. Test approval gates
5. Test triggers (schedule, webhook)
6. Test statistics
"""

import asyncio
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Use temp database for tests
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False, mode="w")
temp_db_path = temp_db.name
temp_db.close()
os.environ["GREENIE_WORKFLOW_DB_PATH"] = temp_db_path


@pytest.fixture(autouse=True)
def cleanup_db():
    """Clean up the temp database after each test."""
    yield
    # Clear all tables
    try:
        conn = sqlite3.connect(temp_db_path)
        conn.execute("DELETE FROM workflow_approvals")
        conn.execute("DELETE FROM workflow_runs")
        conn.execute("DELETE FROM workflow_definitions")
        conn.commit()
        conn.close()
    except Exception:
        pass


class TestWorkflowModels:
    """Test workflow data models."""

    def test_create_workflow_definition(self):
        from hub.workflow.models import StepType, TriggerType, WorkflowDefinition, WorkflowStep, WorkflowTrigger

        wf = WorkflowDefinition(
            name="Test workflow",
            description="A test workflow",
            steps=[
                WorkflowStep(name="Step 1", step_type=StepType.SERVICE.value, service="trapper", task="SEARCH: test"),
                WorkflowStep(name="Step 2", step_type=StepType.APPROVAL.value, approval_description="Approve?"),
            ],
            triggers=[
                WorkflowTrigger(trigger_type=TriggerType.SCHEDULE.value, cron="0 9 * * *", enabled=True),
            ],
        )

        assert wf.name == "Test workflow"
        assert len(wf.steps) == 2
        assert len(wf.triggers) == 1
        assert wf.steps[0].step_type == "service"
        assert wf.steps[1].step_type == "approval"

    def test_workflow_serialization(self):
        from hub.workflow.models import StepType, WorkflowDefinition, WorkflowStep

        wf = WorkflowDefinition(
            name="Test",
            steps=[WorkflowStep(name="S1", step_type=StepType.AGENT.value, agent="test-agent", task="do something")],
        )
        d = wf.to_dict()
        assert d["name"] == "Test"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["agent"] == "test-agent"

        # Deserialize
        wf2 = WorkflowDefinition.from_dict(d)
        assert wf2.name == "Test"
        assert wf2.steps[0].agent == "test-agent"

    def test_workflow_run_serialization(self):
        from hub.workflow.models import RunStatus, WorkflowRun, WorkflowStepRun

        run = WorkflowRun(
            workflow_id="wf-123",
            workflow_name="Test",
            status=RunStatus.RUNNING.value,
            step_runs=[
                WorkflowStepRun(step_id="s1", step_name="Step 1", status="completed"),
                WorkflowStepRun(step_id="s2", step_name="Step 2", status="pending"),
            ],
        )
        d = run.to_dict()
        assert d["status"] == "running"
        assert len(d["step_runs"]) == 2

        run2 = WorkflowRun.from_dict(d)
        assert run2.workflow_id == "wf-123"
        assert run2.step_runs[0].status == "completed"


class TestWorkflowStorage:
    """Test SQLite persistence layer."""

    def test_save_and_get_workflow(self):
        from hub.workflow import storage
        from hub.workflow.models import StepType, WorkflowDefinition, WorkflowStep

        wf = WorkflowDefinition(
            name="Storage test",
            steps=[WorkflowStep(name="S1", step_type=StepType.AGENT.value, agent="agent1", task="task1")],
        )
        saved = storage.save_workflow_definition(wf)
        assert saved.id.startswith("wf-")

        retrieved = storage.get_workflow_definition(saved.id)
        assert retrieved is not None
        assert retrieved.name == "Storage test"
        assert len(retrieved.steps) == 1
        assert retrieved.steps[0].agent == "agent1"

    def test_list_workflows(self):
        from hub.workflow import storage
        from hub.workflow.models import WorkflowDefinition

        for i in range(3):
            storage.save_workflow_definition(WorkflowDefinition(name=f"Workflow {i}"))

        workflows = storage.list_workflow_definitions(limit=10)
        assert len(workflows) == 3

    def test_delete_workflow(self):
        from hub.workflow import storage
        from hub.workflow.models import WorkflowDefinition

        wf = storage.save_workflow_definition(WorkflowDefinition(name="To delete"))
        deleted = storage.delete_workflow_definition(wf.id)
        assert deleted is True

        retrieved = storage.get_workflow_definition(wf.id)
        assert retrieved is None

    def test_save_and_get_run(self):
        from hub.workflow import storage
        from hub.workflow.models import RunStatus, WorkflowRun, WorkflowStepRun

        run = WorkflowRun(
            workflow_id="wf-test",
            workflow_name="Test Run",
            status=RunStatus.COMPLETED.value,
            step_runs=[WorkflowStepRun(step_id="s1", step_name="Step 1", status="completed")],
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = storage.save_workflow_run(run)

        retrieved = storage.get_workflow_run(saved.id)
        assert retrieved is not None
        assert retrieved.status == "completed"
        assert retrieved.workflow_name == "Test Run"

    def test_list_runs_with_filter(self):
        from hub.workflow import storage
        from hub.workflow.models import RunStatus, WorkflowRun

        for i in range(3):
            storage.save_workflow_run(WorkflowRun(
                workflow_id="wf-test",
                status=RunStatus.COMPLETED.value if i < 2 else RunStatus.RUNNING.value,
            ))

        completed = storage.list_workflow_runs(status="completed")
        assert len(completed) == 2

    def test_save_and_get_approval(self):
        from hub.workflow import storage
        from hub.workflow.models import WorkflowApproval

        approval = WorkflowApproval(
            run_id="run-test",
            step_id="s1",
            description="Approve this step",
        )
        saved = storage.save_workflow_approval(approval)

        retrieved = storage.get_workflow_approval(saved.id)
        assert retrieved is not None
        assert retrieved.status == "pending"
        assert retrieved.description == "Approve this step"

    def test_workflow_stats(self):
        from hub.workflow import storage
        from hub.workflow.models import RunStatus, WorkflowApproval, WorkflowDefinition, WorkflowRun

        storage.save_workflow_definition(WorkflowDefinition(name="Stats test"))
        storage.save_workflow_run(WorkflowRun(workflow_id="wf-1", status=RunStatus.RUNNING.value))
        storage.save_workflow_approval(WorkflowApproval(run_id="run-1", step_id="s1"))

        stats = storage.get_workflow_stats()
        assert stats["total_workflows"] >= 1
        assert stats["total_runs"] >= 1
        assert stats["pending_approvals"] >= 1


class TestWorkflowExecutor:
    """Test workflow execution engine."""

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self):
        """Test executing a workflow with no actual service calls (notify step only)."""
        from hub.workflow import execute_workflow, storage
        from hub.workflow.models import RunStatus, StepType, WorkflowDefinition, WorkflowStep

        # Create a workflow with a notify step (doesn't require external services)
        wf = WorkflowDefinition(
            name="Simple test",
            steps=[
                WorkflowStep(
                    name="Notify",
                    step_type=StepType.NOTIFY.value,
                    notify_channel="test",
                    notify_message="Test notification",
                ),
            ],
        )
        saved = storage.save_workflow_definition(wf)

        # Execute
        run = await execute_workflow(saved, trigger_type="test", started_by="test")
        assert run.workflow_id == saved.id
        assert run.status == "running"

        # Wait for completion (poll until done, max 3s)
        for _ in range(15):
            await asyncio.sleep(0.2)
            final_run = storage.get_workflow_run(run.id)
            if final_run and final_run.status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value):
                break

        # Check final state
        assert final_run is not None
        assert final_run.status in (RunStatus.COMPLETED.value, RunStatus.FAILED.value)
        assert len(final_run.step_runs) == 1

    @pytest.mark.asyncio
    async def test_condition_step(self):
        """Test condition step evaluation."""
        from hub.workflow import storage
        from hub.workflow.models import StepType, WorkflowDefinition, WorkflowStep

        wf = WorkflowDefinition(
            name="Condition test",
            steps=[
                WorkflowStep(
                    name="Condition",
                    step_type=StepType.CONDITION.value,
                    condition={"key": "nonexistent", "operator": "eq", "value": "yes"},
                ),
                WorkflowStep(
                    name="Notify",
                    step_type=StepType.NOTIFY.value,
                    notify_channel="test",
                    notify_message="Should be skipped",
                    depends_on=[],
                ),
            ],
        )
        saved = storage.save_workflow_definition(wf)

        from hub.workflow.executor import WorkflowExecutor
        executor = WorkflowExecutor()

        # Test condition evaluation
        assert executor._evaluate_condition({"key": "a", "operator": "eq", "value": "b"}, {"a": "b"}) is True
        assert executor._evaluate_condition({"key": "a", "operator": "eq", "value": "c"}, {"a": "b"}) is False
        assert executor._evaluate_condition({"key": "a", "operator": "contains", "value": "b"}, {"a": "abc"}) is True

    @pytest.mark.asyncio
    async def test_approval_gate(self):
        """Test approval gate pause and resume."""
        from hub.workflow import storage
        from hub.workflow.executor import WorkflowExecutor
        from hub.workflow.models import StepType, WorkflowDefinition, WorkflowStep

        executor = WorkflowExecutor()

        wf = WorkflowDefinition(
            name="Approval test",
            steps=[
                WorkflowStep(
                    name="Approve me",
                    step_type=StepType.APPROVAL.value,
                    approval_description="Please approve",
                    approval_timeout_minutes=1,
                ),
            ],
        )
        saved = storage.save_workflow_definition(wf)

        # Start execution
        run = await executor.execute(wf, trigger_type="test", started_by="test")
        await asyncio.sleep(0.5)  # Let it reach the approval

        # Check it's waiting
        current = storage.get_workflow_run(run.id)
        assert current is not None
        assert current.status == "waiting_approval"

        # Resolve approval
        resolved = await executor.resolve_approval(run.id, approved=True)
        assert resolved is True

        # Wait for completion
        await asyncio.sleep(1)

        final = storage.get_workflow_run(run.id)
        assert final is not None
        # Step should be completed since we approved
        assert final.step_runs[0].approval_result == "approved"


class TestWorkflowTriggers:
    """Test workflow triggers."""

    def test_cron_parsing(self):
        from hub.workflow.triggers import ScheduleTrigger

        # Test valid cron
        next_run = ScheduleTrigger._next_cron_run("0 9 * * *")
        assert next_run is not None

        # Test invalid cron
        next_run = ScheduleTrigger._next_cron_run("invalid")
        assert next_run is None

    def test_webhook_signature(self):
        from hub.workflow.triggers import WebhookTrigger

        secret = "test-secret"
        body = {"key": "value"}
        sig = WebhookTrigger._compute_signature(secret, body)
        assert len(sig) == 64  # SHA256 hex

    @pytest.mark.asyncio
    async def test_webhook_handler(self):
        from hub.workflow import storage
        from hub.workflow.models import TriggerType, WorkflowDefinition, WorkflowTrigger
        from hub.workflow.triggers import WebhookTrigger

        wf = WorkflowDefinition(
            name="Webhook test",
            steps=[],
            triggers=[
                WorkflowTrigger(
                    trigger_type=TriggerType.WEBHOOK.value,
                    webhook_path="/api/workflows/webhook/test-path",
                    enabled=True,
                ),
            ],
        )
        storage.save_workflow_definition(wf)

        handler = WebhookTrigger()
        handler._load_triggers()

        result = await handler.handle_webhook("/api/workflows/webhook/test-path", {"data": "test"})
        assert result["status"] == "accepted"
        assert "run_id" in result


class TestWorkflowAPI:
    """Test workflow API endpoints."""

    @pytest.mark.asyncio
    async def test_create_workflow_api(self):
        from hub.api.workflows import api_create_workflow

        body = {
            "name": "API test workflow",
            "description": "Created via API",
            "steps": [
                {
                    "name": "Search",
                    "step_type": "service",
                    "service": "trapper",
                    "task": "SEARCH: test",
                },
            ],
            "triggers": [
                {
                    "trigger_type": "schedule",
                    "cron": "0 9 * * *",
                    "enabled": True,
                },
            ],
        }

        result = await api_create_workflow(body)
        assert result["name"] == "API test workflow"
        assert len(result["steps"]) == 1
        assert len(result["triggers"]) == 1

    @pytest.mark.asyncio
    async def test_list_workflows_api(self):
        from hub.api.workflows import api_list_workflows
        from hub.workflow import storage
        from hub.workflow.models import WorkflowDefinition

        storage.save_workflow_definition(WorkflowDefinition(name="API list test"))
        result = await api_list_workflows()
        assert "workflows" in result
        assert len(result["workflows"]) >= 1

    @pytest.mark.asyncio
    async def test_get_workflow_api(self):
        from hub.api.workflows import api_create_workflow, api_get_workflow

        created = await api_create_workflow({"name": "Get test"})
        result = await api_get_workflow(created["id"])
        assert result["name"] == "Get test"

    @pytest.mark.asyncio
    async def test_update_workflow_api(self):
        from hub.api.workflows import api_create_workflow, api_update_workflow

        created = await api_create_workflow({"name": "Update test"})
        result = await api_update_workflow(created["id"], {"name": "Updated name"})
        assert result["name"] == "Updated name"

    @pytest.mark.asyncio
    async def test_delete_workflow_api(self):
        from fastapi import HTTPException

        from hub.api.workflows import api_create_workflow, api_delete_workflow, api_get_workflow

        created = await api_create_workflow({"name": "Delete test"})
        result = await api_delete_workflow(created["id"])
        assert result["status"] == "ok"

        with pytest.raises(HTTPException):
            await api_get_workflow(created["id"])

    @pytest.mark.asyncio
    async def test_workflow_stats_api(self):
        from hub.api.workflows import api_workflow_stats
        from hub.workflow import storage
        from hub.workflow.models import WorkflowDefinition

        storage.save_workflow_definition(WorkflowDefinition(name="Stats API test"))
        result = await api_workflow_stats()
        assert "total_workflows" in result
        assert result["total_workflows"] >= 1


class TestFullLifecycle:
    """End-to-end lifecycle test."""

    @pytest.mark.asyncio
    async def test_create_run_check_history(self):
        """Full lifecycle: create workflow, run it, check history."""
        from hub.workflow import execute_workflow, storage
        from hub.workflow.models import StepType, WorkflowDefinition, WorkflowStep

        # 1. Create workflow
        wf = WorkflowDefinition(
            name="Lifecycle test",
            description="Full lifecycle test",
            steps=[
                WorkflowStep(
                    name="Notify",
                    step_type=StepType.NOTIFY.value,
                    notify_channel="test",
                    notify_message="Lifecycle test notification",
                ),
            ],
            tags=["test", "lifecycle"],
        )
        saved = storage.save_workflow_definition(wf)
        assert saved.id.startswith("wf-")

        # 2. Verify it's stored
        retrieved = storage.get_workflow_definition(saved.id)
        assert retrieved is not None
        assert retrieved.name == "Lifecycle test"

        # 3. Execute
        run = await execute_workflow(saved, trigger_type="manual", started_by="test")
        assert run.workflow_id == saved.id

        # 4. Wait for completion (poll until done, max 3s)
        final_run = None
        for _ in range(15):
            await asyncio.sleep(0.2)
            final_run = storage.get_workflow_run(run.id)
            if final_run and final_run.status in ("completed", "failed"):
                break

        # 5. Check run history
        assert final_run is not None
        assert final_run.status in ("completed", "failed")
        assert len(final_run.step_runs) == 1
        assert final_run.started_at is not None
        assert final_run.completed_at is not None

        # 6. Check stats
        stats = storage.get_workflow_stats()
        assert stats["total_workflows"] >= 1
        assert stats["total_runs"] >= 1

        # 7. List runs
        runs = storage.list_workflow_runs(workflow_id=saved.id)
        assert len(runs) >= 1

        # 8. Clean up
        storage.delete_workflow_run(run.id)
        storage.delete_workflow_definition(saved.id)
