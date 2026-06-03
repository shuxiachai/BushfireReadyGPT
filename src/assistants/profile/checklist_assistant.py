from src.assistants.assistant import Assistant
from src.config import client, model
import streamlit as st
from src.utils import get_llm_response, stream_static_text, TEXT_CURSOR


def verify_location_on_map(lat, lon):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.location_confirmed = False
    return "Ask the client to confirm the location by clicking the 'Confirm Location' button."

class ChecklistAssistant(Assistant):
    def __init__(self, config_path, update_assistant, checklist=None):
        self.checklist = checklist
        super().__init__(config_path, update_assistant)
        self.function_dict = {
            "checklist_complete": self.checklist_complete,
            "checklist_update": self.checklist_update,
            "verify_location_on_map": verify_location_on_map
        }
        if checklist is not None:
            self.init_message_sent = True
        else:
            self.init_message_sent = False

    def initialize_instructions(self):
        if self.checklist is not None:
            check_list = self.checklist
        else:
            check_list = self.config["initial_checklist"]
        return self.config["instructions"] + "\n" + check_list
    
    def get_assistant_response(self, user_message=None, thread_id=None):
        if user_message:
            #return super().get_assistant_response(user_message = user_message + "\n\nUpon completing the checklist, share your checklist with me to confirm the accuracy of the information.\nWhen you are all done, call the function `checklist_complete()` with your completed checklist.", thread_id = thread_id)
            return super().get_assistant_response(user_message = user_message, thread_id = thread_id)
        else:
            if not self.init_message_sent:
                self.add_assistant_message("Let's get started with our first question: What Australian location are you concerned about for bushfire preparedness or resilience?", thread_id)
                self.init_message_sent = True
                stream_static_text(self.config['init_message'])
                return self.config['init_message'], None, []
            return super().get_assistant_response(thread_id = thread_id)
    

    def checklist_update(self, checklist: str):
        if self.checklist is not None:
            return "Checklist has already been updated."
        
        stream_static_text(f"I'd like to take a moment to formulate a few focused follow-up questions so I can tailor the bushfire resilience plan to your situation. Please don't feel any pressure if you're unsure about some answers. Please do not respond yet ...{TEXT_CURSOR}")

        follow_up = client.chat.completions.create(
            model=model,
            messages = [
                {"role": "system", "content": self.config["follow_up_instructions"]},
                {"role": "user", "content": checklist}
                ],
            top_p=0.95,
            ).choices[0].message
        
        updated_checklist = get_llm_response(
            messages = [
                follow_up,
                {"role": "system", "content": self.config["format_instructions"]}
                ],
        )
        
        updated_checklist += "\n\nFor each question on the checklist, ask the client if they are interested in addressing it in today's bushfire resilience session. \n\n**After you confirm the accuracy of all the information, call the function `checklist_complete()` with your completed checklist.**"
        args = {
            "checklist": checklist + "\n" + updated_checklist
        }
        
        self.update_assistant("FollowUpAssistant", args)

        return "Checklist has been updated. Please tell your client that you have a few more follow-up questions about the scope of this bushfire resilience session and ask whether they are ready to proceed."
        
    def checklist_complete(self, checklist: str):
        with open("chat_history/user_profile.txt", "w", encoding="utf-8") as file:
            file.write(checklist)
        return (
            "Checklist saved. Continue with the current BushfireReadyGPT report workflow; "
            "the legacy planning route is no longer used in this project."
        )
