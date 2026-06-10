import sys
import os
from types import ModuleType

# Mock the missing audioop module for Python 3.13 compatibility
if 'audioop' not in sys.modules:
    mock_audioop = ModuleType('audioop')
    mock_audioop.error = Exception
    # Add dummy functions required by pydub/gradio if needed
    mock_audioop.getsample = lambda data, width, index: 0
    sys.modules['audioop'] = mock_audioop

import gradio as gr

def greet(name):
    return f"Hello, {name}! Welcome to ViralMint."

demo = gr.Interface(fn=greet, inputs="text", outputs="text")
demo.launch(
    server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
    server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    share=False
)