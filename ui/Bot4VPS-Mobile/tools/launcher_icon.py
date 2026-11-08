#!/usr/bin/env python3
"""Generate the Android vector foreground from the redrawn web robot (no bitmap)."""
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
ANDROID = "http://schemas.android.com/apk/res/android"
AAPT = "http://schemas.android.com/aapt"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("android", ANDROID)
ET.register_namespace("aapt", AAPT)


def generate() -> Path:
    source = ET.parse(ROOT / "tools/artwork/launcher.svg").getroot()
    gradients = {node.attrib["id"]: node for node in source.iter(f"{{{SVG}}}linearGradient")}
    vector = ET.Element("vector", {
        f"{{{ANDROID}}}width": "108dp", f"{{{ANDROID}}}height": "108dp",
        f"{{{ANDROID}}}viewportWidth": "108", f"{{{ANDROID}}}viewportHeight": "108",
    })
    for node in source.findall(f"{{{SVG}}}path"):
        path = ET.SubElement(vector, "path", {f"{{{ANDROID}}}pathData": node.attrib["d"]})
        fill = node.attrib["fill"]
        if fill.startswith("url(#"):
            gradient = gradients[fill[5:-1]]
            attr = ET.SubElement(path, f"{{{AAPT}}}attr", {"name": "android:fillColor"})
            result = ET.SubElement(attr, "gradient", {f"{{{ANDROID}}}type": "linear"})
            for svg_name, android_name in [("x1", "startX"), ("y1", "startY"), ("x2", "endX"), ("y2", "endY")]:
                result.set(f"{{{ANDROID}}}{android_name}", gradient.attrib[svg_name])
            for stop in gradient:
                ET.SubElement(result, "item", {
                    f"{{{ANDROID}}}color": stop.attrib["stop-color"],
                    f"{{{ANDROID}}}offset": stop.attrib["offset"],
                })
        else:
            path.set(f"{{{ANDROID}}}fillColor", fill)
    ET.indent(vector, space="    ")
    target = ROOT / "app/src/main/res/drawable/ic_launcher_foreground.xml"
    ET.ElementTree(vector).write(target, encoding="utf-8", xml_declaration=True)
    with target.open("ab") as stream:
        stream.write(b"\n")
    return target


if __name__ == "__main__":
    print(generate())
