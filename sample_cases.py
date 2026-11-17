import json


_FORMAT = "python-grader-sample-cases-v1"


def _decode_sample_values(value):
    try:
        payload = json.loads(value or "")
    except (TypeError, ValueError):
        return None
    if (
        isinstance(payload, dict)
        and payload.get("format") == _FORMAT
        and isinstance(payload.get("values"), list)
    ):
        return [item if isinstance(item, str) else "" for item in payload["values"]]
    return None


def sample_examples_from_values(sample_input, sample_output):
    inputs = _decode_sample_values(sample_input)
    outputs = _decode_sample_values(sample_output)
    if inputs is None and outputs is None:
        if sample_input or sample_output:
            return [{"input": sample_input or "", "output": sample_output or ""}]
        return []

    inputs = inputs if inputs is not None else [sample_input or ""]
    outputs = outputs if outputs is not None else [sample_output or ""]
    count = max(len(inputs), len(outputs))
    return [
        {
            "input": inputs[index] if index < len(inputs) else "",
            "output": outputs[index] if index < len(outputs) else "",
        }
        for index in range(count)
    ]


def sample_fields_from_payload(data):
    if "sample_examples" not in data:
        return data.get("sample_input", ""), data.get("sample_output", "")

    examples = data["sample_examples"]
    if not isinstance(examples, list):
        raise ValueError("Danh sách Input/Output mẫu không hợp lệ.")

    inputs = []
    outputs = []
    for example in examples:
        if not isinstance(example, dict):
            raise ValueError("Mỗi mẫu cần có Input và Output.")
        sample_input = example.get("input", "")
        sample_output = example.get("output", "")
        if not isinstance(sample_input, str) or not isinstance(sample_output, str):
            raise ValueError("Input và Output mẫu phải là văn bản.")
        if not sample_input.strip() and not sample_output.strip():
            continue
        inputs.append(sample_input)
        outputs.append(sample_output)

    if not inputs:
        return "", ""

    return (
        json.dumps({"format": _FORMAT, "values": inputs}, ensure_ascii=False),
        json.dumps({"format": _FORMAT, "values": outputs}, ensure_ascii=False),
    )
