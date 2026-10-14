# Pictures and screenshots

Emvryx 2 models read text only; Emvryx 3 models (Qwen3.5 bases) can look at pictures themselves. Three things make pictures work in the chat.

**0. The model looks itself (Emvryx 3).** When a model has its own picture reader, `mmproj.gguf` in the same folder as its `.gguf` (`app/app_runner.py`
`projector_for`), llama-server is started with `--mmproj` and a picture goes straight into the prompt, just before the question (`app_engine.with_pictures`,
llama-server's `multimodal_data`). Nothing is turned into words first, so code keeps its indentation and the model can say what it means. The training
chain's **eyes** step (`scripts/export_projector.py`) makes that file from the base model and checks the tuned model reads a number off a picture; when the
check fails the file is set aside (`mmproj.gguf.failed`) and the two ways below are used for that model, as before.

**1. Reading the words in a picture (always on).** `app/documents.py` reads the text in a screenshot or photo (needs `pip install rapidocr-onnxruntime`, in requirements.txt). A picture without words says so plainly.

**2. Looking at the picture (optional vision helper).** `app/vision.py` runs a small vision model beside the chat model. It writes down what the picture shows and every word on it, who said what in a chat or post, and the chosen Emvryx model answers from that description (shown under the reply as "Looked at 1 picture"). It starts on the first picture and stops after 10 idle minutes, so it does not hold graphics memory for nothing.

Setup (once, about 3 GB):
```
python scripts/get_vision_model.py
```
Then restart the app. The files land in `export/open/vision/` (a model `.gguf` and its `mmproj` `.gguf`); the app finds them by itself, or pass `--vision-gguf` and `--vision-mmproj`. It needs a recent `llama-server` (one that accepts `--mmproj`). Check the model's licence on its Hugging Face page before using it in a product.

How it behaves:
- A picture goes with the message you send it with, shows as a small preview in the box and then in your message, and is not sent again with later messages. Follow-up questions in the same chat still see it.
- Without the helper, the chat says "Read the text in the picture (it can't see photos yet)".
- A description is remembered for the same picture and question, so asking again is quick.
- Pictures are kept in your own documents (`docs-<you>.db`) and are in "Download my data".

Not tested against a real vision model yet (this was built with a stand-in), so the first real run may need small fixes.
