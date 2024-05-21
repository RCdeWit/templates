"""
Preprocessing utilities for evaluation.
"""

import re
from typing import Tuple, Dict, Any, List
from functools import partial

import ray.data

from fc_utils.function_extraction_utils import (
    parse_tool_result,
    get_tool_calls_from_response,
)
from fc_utils.preprocessing import extract_functions_from_system_msg, InvalidRoleError
from fc_utils.data_format import IndicatorTags, DEFAULT_SYSTEM_PROMPT, DatasetFormat


def anyscale_to_openai_response(
    message: Dict[str, Any], tool_call_tags: IndicatorTags
) -> Dict[str, Any]:
    """Parse Anyscale-formatted message and convert to the OpenAI format

    Args:
        message: The message to parse in the Anyscale format
        tool_call_tags: Tuple containing the start and end tags for the tool call

    Returns:
        openai_response: The response in the OpenAI format with the following fields:
            role: The role of the message
            content: The content of the message
            tool_calls: The tool calls extracted from the message
    """
    content = message["content"]
    tool_calls = None
    if tool_call_tags.start in message["content"]:
        content, tool_calls = get_tool_calls_from_response(
            message["content"],
            tool_call_tags=tool_call_tags,
            format=DatasetFormat.ANYSCALE,
        )
    openai_response = {
        "role": message["role"],
        "content": content,
        "tool_calls": tool_calls,
    }
    return openai_response


def test_mapper_openai(
    example: Dict[str, Any],
    tool_call_tags: IndicatorTags,
    tool_result_tags: IndicatorTags,
    tool_list_tags: IndicatorTags,
) -> Dict[str, Any]:
    """
    Processes test data example for evaluation with an OpenAI model.

    The input example is expected to be in the Anyscale format, and the output is in the OpenAI format.

    Args:
        example: The test example to preprocess
        tool_call_tags: Tuple containing the start and end tags for the tool call in the assistant response
        tool_result_tags: Tuple containing the start and end tags for the tool result in the user message
        tool_list_tags: Tuple containing the start and end tags for the tool list

    Returns:
        example: The preprocessed test example in the OpenAI format
    """
    assert len(example["messages"]) > 0, "Example messages should not be empty"
    assert (
        example["messages"][0]["role"] == "system"
    ), "First message should be a system message"
    # Convert the messages to a list in case it's in an array format
    example["messages"] = list(example["messages"])
    messages = example["messages"]
    # The first message is the system message.
    system_msg = {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}
    processed_messages = [system_msg]
    # The test example has tool list included in the message, so we extract the tools from the system message
    tools = []
    if tool_list_tags.start in messages[0]["content"]:
        tools = extract_functions_from_system_msg(
            messages[0]["content"],
            format=DatasetFormat.ANYSCALE,
            tool_list_tags=tool_list_tags,
        )

    for message in messages[1:]:
        if message["role"] == "user":
            # Check if the message contains a tool result
            if tool_result_tags.start in message["content"]:
                # Parse the tool result and convert the message to role tool
                tool_response = parse_tool_result(message["content"], tool_result_tags)
                # Use the name, tool_call_id and content fields
                openai_message = {
                    "role": "tool",
                    "tool_call_id": tool_response["tool_call_id"],
                    "name": tool_response["name"],
                    "content": tool_response["content"],
                }
                processed_messages.append(openai_message)
            else:
                processed_messages.append(message)
        elif message["role"] == "assistant":
            expected_response = anyscale_to_openai_response(message, tool_call_tags)
            processed_messages.append(expected_response)
        else:
            InvalidRoleError(f"Invalid role {message['role']} found in the message")

    return {"messages": processed_messages, "tools": tools}


def test_mapper_anyscale(
    example: Dict[str, Any], tool_call_tags: IndicatorTags
) -> Dict[str, Any]:
    """
    Processes test data example for evaluation with an Anyscale Endpoints model.

    The input example is expected to be in the Anyscale format. In the output, the assistant messages are converted to the OpenAI format for evaluation.
    The user and system messages remain the same.

    Args:
        example: The test example to preprocess
        tool_call_tags: Tuple containing the start and end tags for the tool call

    Returns:
        example: The preprocessed test example
    """
    if not example["messages"] or example["messages"][0]["role"] != "system":
        raise ValueError("First message should be a system message")
    processed_messages = []
    for message in example["messages"]:
        # User messages should remain the same, but the ground truth assistant responses
        # Need to be converted to the OpenAI format
        if message["role"] in ["user", "system"]:
            processed_messages.append(message)
        elif message["role"] == "assistant":
            expected_response = anyscale_to_openai_response(message, tool_call_tags)
            processed_messages.append(expected_response)
        else:
            InvalidRoleError(f"Invalid role {message['role']} found in the message")
    return {"messages": processed_messages}


def get_evaluation_dataset(
    test_ds: ray.data.Dataset,
    tool_call_tags: IndicatorTags,
    tool_result_tags: IndicatorTags,
    tool_list_tags: IndicatorTags,
    format: DatasetFormat,
) -> List[Dict[str, Any]]:
    """
    Handles the preprocessing of the test dataset for evaluation.

    Args:
        test_ds: The test dataset to preprocess
        tool_call_tags: Tuple containing the start and end tags for the tool call
        tool_result_tags: Tuple containing the start and end tags for the tool result
        format: The expected output data format. OpenAI and Anyscale are supported.

    Returns:
        modified_ds: The preprocessed test dataset
    """
    # Converts test_ds to a list of dicts because the nested structure of the modified dataset is not supported by PyArrow
    if format == DatasetFormat.ANYSCALE:
        test_data_mapper = partial(test_mapper_anyscale, tool_call_tags=tool_call_tags)
    elif format == DatasetFormat.OPENAI:
        test_data_mapper = partial(
            test_mapper_openai,
            tool_call_tags=tool_call_tags,
            tool_result_tags=tool_result_tags,
            tool_list_tags=tool_list_tags,
        )
    else:
        raise NotImplementedError(
            f"Data Format {format} is not supported for evaluation"
        )
    modified_ds = []
    for example in test_ds.iter_rows():
        modified_ds.append(test_data_mapper(example))
    return modified_ds
