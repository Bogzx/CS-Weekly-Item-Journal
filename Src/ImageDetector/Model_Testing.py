import torch
from ultralytics import YOLO
import cv2
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

# 1. Load the pre-trained model
model = YOLO("Models\BOX_TRAINED.pt")  # adjust path to your model file

# 2. Prepare test images (either from a directory or a single test image)
test_image_path = "WeeklyCarePackage_Photos_Sample\cs2-new-drops-system-v0-ithfcqpz7vqb1.webp"  # adjust to your test image

# 3. Run inference
results = model(test_image_path)

# 4. Visualize and analyze results
for r in results:
    # Plot results
    fig, ax = plt.subplots(figsize=(12, 9))
    ax.imshow(cv2.cvtColor(cv2.imread(test_image_path), cv2.COLOR_BGR2RGB))
    
    # Get detection data
    boxes = r.boxes.xyxy.cpu().numpy()
    classes = r.boxes.cls.cpu().numpy()
    confidences = r.boxes.conf.cpu().numpy()
    
    # Display each detection
    for box, cls, conf in zip(boxes, classes, confidences):
        x1, y1, x2, y2 = box
        class_name = model.names[int(cls)]
        
        # Draw rectangle
        rect = plt.Rectangle((x1, y1), x2-x1, y2-y1, fill=False, edgecolor='red', linewidth=2)
        ax.add_patch(rect)
        
        # Add label
        ax.text(x1, y1, f"{class_name}: {conf:.2f}", 
                bbox=dict(facecolor='yellow', alpha=0.5))
    
    plt.axis('off')
    plt.tight_layout()
    plt.show()
    
    # Print detection summary
    print(f"Found {len(boxes)} objects")
    for cls, conf in zip(classes, confidences):
        print(f"- {model.names[int(cls)]}: confidence {conf:.4f}")

# 5. Calculate metrics if you have ground truth annotations
# This would require additional code to load annotations and compute mAP