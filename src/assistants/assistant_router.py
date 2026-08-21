from src.assistants.assistant import clear_thread_messages
from src.assistants.profile import ChecklistAssistant
from src.utils import create_thread


class AssistantRouter:
    def __init__(self, name, thread_id=None, args=None):
        args = args or {}
        self.current_thread = create_thread()
        if thread_id:
            self.current_thread.id = thread_id
        self.new_thread = True

        self.assistant_dict = {
            "ChecklistAssistant": [ChecklistAssistant, "src/assistants/profile/config.yml"],
            "FollowUpAssistant": [ChecklistAssistant, "src/assistants/profile/config_follow_up.yml"],
        }

        Assistant = self.assistant_dict[name][0]
        config_path = self.assistant_dict[name][1]
        self.current_assistant = Assistant(config_path, self.update_assistant, **args)

    def update_assistant(self, name, args, new_thread=False):
        Assistant = self.assistant_dict[name][0]
        config_path = self.assistant_dict[name][1]
        self.current_assistant = Assistant(config_path, self.update_assistant, **args)
        if new_thread:
            self.current_thread = create_thread()
            self.new_thread = True

    def get_assistant_response(self, user_message: str = None) -> str:
        self.new_thread = False
        full_response, run_id, tool_outputs = self.current_assistant.get_assistant_response(
            user_message, self.current_thread.id
        )
        if len(tool_outputs):
            full_response += "\n\n"
            full_response += self.current_assistant.respond_to_tool_output(self.current_thread.id, run_id, tool_outputs)
        elif self.new_thread:
            return self.get_assistant_response()
        if self.current_assistant.visualizations:
            self.pending_visualizations = list(self.current_assistant.visualizations)
            self.current_assistant.visualizations = []
        return full_response if isinstance(full_response, str) else str(full_response)

    def get_governed_response(self, prompt: str) -> str:
        """Run an isolated, tool-free completion for a governed report version."""

        assistant_class, config_path = self.assistant_dict["ChecklistAssistant"]
        isolated_assistant = assistant_class(config_path, self.update_assistant)
        isolated_thread = create_thread()
        try:
            full_response, _run_id, _tool_outputs = isolated_assistant.get_assistant_response(
                prompt,
                isolated_thread.id,
                allow_tools=False,
            )
            return full_response if isinstance(full_response, str) else str(full_response)
        finally:
            clear_thread_messages(isolated_thread.id)

    def clear_model_history(self):
        """Remove this browser session's provider conversation history."""

        clear_thread_messages(self.current_thread.id)

    def resume_conversation(self):
        self.current_thread = create_thread()
        self.new_thread = False
