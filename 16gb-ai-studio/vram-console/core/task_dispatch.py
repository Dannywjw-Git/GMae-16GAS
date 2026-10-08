"""Durable boundary around a nontransactional backend submission.

The caller must already own its GPU reservation. It must retain ownership when
DispatchUncertain is raised, including when the store cannot record ambiguity.
Recovery reconciles the persisted submission ID; it never calls dispatch again.
"""
import uuid

from core.task_store import TaskConflict


class DispatchUncertain(RuntimeError):
    """The backend may be executing; releasing the resource is unsafe."""

    def __init__(self, submission_id, message):
        super().__init__(message)
        self.submission_id = submission_id


class TaskDispatcher:
    def __init__(self, store):
        self.store = store

    def dispatch(self, task, workflow, submit):
        """Commit intent before RPC, then record response before returning.

        submit(workflow, submission_id) returns (prompt_id, error). An explicit
        error object with uncertain=False proves rejection. Exceptions, malformed
        responses and missing responses are ambiguous. Failure to persist after
        attempting RPC is ambiguous even if the response indicates rejection.
        """
        if task['status'] != 'precheck':
            raise TaskConflict('only a prechecked task may be dispatched')
        submission_id = str(uuid.uuid4())
        # If this write fails, submit is never called. CAS also prevents two
        # workers from submitting the same durable task.
        submitting = self.store.checkpoint(
            task['id'], task['version'], 'submitting',
            {'submission_id': submission_id})
        try:
            prompt_id, error = submit(workflow, submission_id)
        except Exception as exc:
            return self._uncertain(submitting, 'backend submission raised: ' + str(exc))
        if isinstance(prompt_id, str) and prompt_id.strip():
            try:
                return self.store.checkpoint(
                    task['id'], submitting['version'], 'running', {'prompt_id': prompt_id})
            except Exception as exc:
                # Never return a success that the durable record cannot prove.
                raise DispatchUncertain(submission_id, 'accepted response could not be saved') from exc
        if isinstance(error, dict) and error.get('uncertain') is False and not prompt_id:
            try:
                return self.store.checkpoint(
                    task['id'], submitting['version'], 'failed',
                    {'error': str(error.get('message', 'backend rejected submission'))})
            except Exception as exc:
                raise DispatchUncertain(submission_id, 'rejection could not be saved') from exc
        return self._uncertain(submitting, 'backend acceptance cannot be determined')

    def _uncertain(self, task, message):
        submission_id = task['checkpoint']['submission_id']
        try:
            self.store.checkpoint(task['id'], task['version'], 'uncertain', {'error': message})
        except Exception as exc:
            raise DispatchUncertain(submission_id, message + '; checkpoint unavailable') from exc
        raise DispatchUncertain(submission_id, message)
