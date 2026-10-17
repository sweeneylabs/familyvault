from pathlib import Path

import cv2
import insightface

# Initialize face detector
app = insightface.app.FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"],
)
app.prepare(ctx_id=0, det_size=(640, 640))

# CHANGE THIS to one of your photos that clearly contains faces
from pathlib import Path

image_path = Path("/Volumes/4TB Thick G-Drive/Media/Photo Library/IMG_8400.JPG")

img = cv2.imread(str(image_path))

if img is None:
    raise RuntimeError(f"Could not read {image_path}")

faces = app.get(img)

print(f"Detected {len(faces)} face(s)")

for i, face in enumerate(faces, start=1):
    x1, y1, x2, y2 = face.bbox.astype(int)

    print(
        f"Face {i}: confidence={face.det_score:.3f}, "
        f"bbox=({x1}, {y1})-({x2}, {y2})"
    )

    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)

output = image_path.with_name(image_path.stem + "_faces.jpg")
cv2.imwrite(str(output), img)

print(f"Saved {output}")