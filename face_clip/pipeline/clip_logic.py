def _largest_box(boxes):
    if not boxes:
        return None
    return max(
        boxes,
        key=lambda b: (b[2] - b[0]) * (b[3] - b[1])
    )


def expand_box(box, frame_w, frame_h, scale=1.3):
    x1, y1, x2, y2 = box
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    w = (x2 - x1) * scale
    h = (y2 - y1) * scale

    nx1 = max(0, int(cx - w / 2))
    ny1 = max(0, int(cy - h / 2))
    nx2 = min(frame_w, int(cx + w / 2))
    ny2 = min(frame_h, int(cy + h / 2))

    return (nx1, ny1, nx2, ny2)


def select_focus(face_boxes, person_boxes, object_boxes, frame_shape):
    """
    Face decides WHO
    Person decides HOW MUCH of the scene
    """

    H, W = frame_shape[:2]

    # 1️⃣ Face → find person containing it
    largest_face = _largest_box(face_boxes)
    if largest_face:
        fx1, fy1, fx2, fy2 = largest_face
        for px1, py1, px2, py2 in person_boxes:
            if fx1 >= px1 and fy1 >= py1 and fx2 <= px2 and fy2 <= py2:
                return expand_box((px1, py1, px2, py2), W, H), "person"

    # 2️⃣ No face → best person
    person = _largest_box(person_boxes)
    if person:
        return expand_box(person, W, H), "person"

    # 3️⃣ Fallback → object
    obj = _largest_box(object_boxes)
    if obj:
        return expand_box(obj, W, H), "object"

    return None, None