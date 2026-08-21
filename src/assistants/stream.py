def check_tool_call(event):
    return event.event == "thread.run.requires_action"


def manage_tool_call(event, on_tool_call_created):
    if event.event != "thread.run.requires_action":
        raise ValueError(f"Unexpected tool-call event: {event.event}")
    tool_outputs = []
    for tool in event.data.required_action.submit_tool_outputs.tool_calls:
        output = on_tool_call_created(tool)
        if output == "Change Thread":
            return []
        tool_outputs.append({"tool_call_id": tool.id, "output": output if output else "Success!"})
    return tool_outputs


def check_message_delta(event):
    return event.event == "thread.message.delta" and event.data.object == "thread.message.delta"


def get_text_stream(event):
    if event.event != "thread.message.delta" or event.data.object != "thread.message.delta":
        raise ValueError(f"Unexpected text-stream event: {event.event}")
    return event.data.delta


def get_text_delta(delta):
    if delta[0] == "content" and delta[1][0].type == "text":
        return delta[1][0].text.value
    return ""
