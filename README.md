# Colour Dropper

Read the colour of any pixel on screen - in any application, not just a browser - with a magnifier, hex/RGB/HSL, and a WCAG contrast check between your last two picks. Borderless and always on top, in Mavis's window style.

A feature for [Mavis AI](https://www.mavis-ai.com) — a desktop voice assistant.

```
You: "open colour dropper"
```

Mavis opens it and stands its own panels down so they are not in your way. Say *"show the interface"* to bring them back.

## Install

From the Mavis Appstore — find **Colour Dropper** and click Install.

Or install it directly:

```python
from utils.feature_install import install_from_github
install_from_github("https://github.com/keefng8/colour-dropper")
```

## What you can say

- *"open colour dropper"*
- *"pick a colour from my screen"*
- *"what colour is that"*
- *"eyedropper"*

These are not matched word for word. Mavis gives them to its language model as examples of intent, so close variations work too.

## How it works

The one thing a web page cannot do: read a pixel from ANY application, not just its own canvas. Raw ctypes against gdi32, so there is no screenshot library and nothing is captured beyond the pixels you ask for. Two details that silently produce wrong colours are handled - COLORREF is 0x00BBGGRR, so reading it as RGB swaps red and blue, and a display scaled above 100% needs DPI awareness or the sample comes from the wrong place.

## Requirements

None. A single HTML file — it runs in your browser, offline, and nothing leaves your machine.

## Building your own

See [Building features for Mavis](https://github.com/keefng8/mavis-feature-docs) — a feature is just a GitHub repository with a `mavis.json`.

## License

MIT — see [LICENSE](LICENSE).
