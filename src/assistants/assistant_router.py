from src.assistants.profile import ChecklistAssistant
from src.utils import create_thread


class AssistantRouter:
    def __init__(self, name, thread_id=None, args={}):
        self.current_thread = create_thread()
        if thread_id:
            self.current_thread.id = thread_id
        self.new_thread = True

        with open("chat_history/threads.txt", "a", encoding="utf-8") as f:
            f.write(f"{self.current_thread.id}\n")

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
            with open("chat_history/threads.txt", "a", encoding="utf-8") as f:
                f.write(f"{self.current_thread.id}\n")
            self.new_thread = True

    def get_assistant_response(self, user_message: str = None) -> str:
        self.new_thread = False
        full_response, run_id, tool_outputs = self.current_assistant.get_assistant_response(user_message, self.current_thread.id)
        if len(tool_outputs):
            full_response += "\n\n"
            full_response += self.current_assistant.respond_to_tool_output(self.current_thread.id, run_id, tool_outputs)
        elif self.new_thread:
            return self.get_assistant_response()
        if self.current_assistant.visualizations:
            self.pending_visualizations = list(self.current_assistant.visualizations)
            self.current_assistant.visualizations = []
        return full_response if isinstance(full_response, str) else str(full_response)

    def resume_conversation(self):
        self.current_thread = create_thread()
        self.new_thread = False
        with open("chat_history/threads.txt", "a", encoding="utf-8") as f:
            f.write(f"{self.current_thread.id}\n")
