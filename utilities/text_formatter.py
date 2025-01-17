import markdown
def format_testcase(text):
  """
  Formats requirements and test cases in markdown format.

  Args:
    text: The text containing the requirements and test cases.

  Returns:
    A string with the formatted text in markdown.
  """

  lines = text.splitlines()
  formatted_text = ""
  current_section = ""

  for line in lines:
    line = line.strip()
    if line.startswith("Requirement:"):
      formatted_text += f"\n**{line}**\n\n"
      current_section = "Requirement"
    elif line.startswith("Test Case"):
      formatted_text += f"\n**{line}:**\n\n"
      current_section = "Test Case"
    elif line and current_section == "Test Case":
      formatted_text += f"{line.split('. ', 1)[0]}. {line.split('. ', 1)[1]}\n"  # Add number and indent
    else:
      formatted_text += f"{line}\n"

  return formatted_text



def format_bdd_scenarios(input_text):
    """
    Formats BDD scenarios from single-line input into a markdown-based HTML page.

    :param input_text: A single string containing all scenarios in a single-line format.
    :param output_file: The name of the HTML output file.
    """
    # Split input into individual scenarios
    scenarios = input_text.strip().split("Scenario:")
    scenarios = [scenario.strip() for scenario in scenarios if scenario.strip()]

    # Initialize Markdown content
    markdown_content = "# BDD Scenarios\n\n"

    # Process each scenario
    for scenario in scenarios:
        # Extract title and steps
        title, *steps = scenario.split("Given")
        title = title.strip()
        steps_text = "Given" + " ".join(steps).strip()

        # Format the markdown content
        markdown_content += f"## Scenario: {title}\n"
        for line in steps_text.split(" And "):
            if "When" in line:
                markdown_content += f"**When** {line.split('When')[1].strip()}\n\n"
            elif "Then" in line:
                markdown_content += f"**Then** {line.split('Then')[1].strip()}\n\n"
            elif "Given" in line:
                markdown_content += f"**Given** {line.split('Given')[1].strip()}\n\n"
            elif "But" in line:
                markdown_content += f"**But** {line.split('But')[1].strip()}\n\n"
            else:
                markdown_content += f"**And** {line.strip()}\n\n"

    # Convert Markdown to HTML
    return markdown.markdown(markdown_content)