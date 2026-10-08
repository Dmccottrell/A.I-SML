# Pictures and screenshots

The Emvryx models read text only. Two things make pictures work in the chat.

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
