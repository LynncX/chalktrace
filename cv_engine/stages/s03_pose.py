"""人体框投影覆盖率；保守估计遮挡，不将其等同真实遮挡或教师身份。"""
import cv2
import numpy as np

SKELETON = ((0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9),
            (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16))


def project_people(people, calibration):
    width, height = calibration["output_size"]
    mask = np.zeros((height, width), dtype="uint8")
    matrix = np.array(calibration["source_to_board"], dtype="float64")
    for person in people:
        x1, y1, x2, y2 = person["bbox"]
        poly = cv2.perspectiveTransform(np.float32([[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]), matrix)[0]
        cv2.fillConvexPoly(mask, np.rint(poly).astype("int32"), 255)
    return mask, float(np.count_nonzero(mask) / mask.size)


def pose_overlay(image, people, occlusion):
    output = image.copy()
    for person in people:
        x1, y1, x2, y2 = np.rint(person["bbox"]).astype("int32")
        cv2.rectangle(output, (x1, y1), (x2, y2), (60, 130, 255), 3)
        kpts = person["keypoints"]
        for a, b in SKELETON:
            if kpts[a][2] >= .4 and kpts[b][2] >= .4:
                cv2.line(output, tuple(np.rint(kpts[a][:2]).astype("int32")),
                         tuple(np.rint(kpts[b][:2]).astype("int32")), (70, 220, 70), 2)
        for x, y, score in kpts:
            if score >= .4:
                cv2.circle(output, (round(x), round(y)), 4, (0, 220, 255), -1)
    cv2.rectangle(output, (0, 0), (image.shape[1], 38), (20, 20, 20), -1)
    cv2.putText(output, f"people={len(people)}  bbox/board={occlusion:.1%} (estimate)",
                (10, 26), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 2)
    return output
