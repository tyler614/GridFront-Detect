package io.gridfront.scout

import org.json.JSONArray
import org.json.JSONObject

/**
 * Static catalog of detection models the OAK firmware can run.
 *
 * The .blob files live host-side under detect.gridfront.io/models/ and
 * are baked into the OAK at flash time by build_standalone_v2.py. This
 * registry is *informational* — the tablet uses it to render the picker
 * and remember the active selection. Switching models still requires
 * reflashing the camera from the build host; the Kotlin side just
 * persists the choice in config.json so the next flash picks it up.
 */
object ModelRegistry {

    data class Model(
        val id: String,
        val name: String,
        val description: String,
        val classes: List<String>,
        val inputSize: Pair<Int, Int>,
        val source: String,           // "local" | "hubai"
    ) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("id", id)
            put("name", name)
            put("description", description)
            put("classes", JSONArray(classes))
            put("class_count", classes.size)
            put("input_size", JSONArray(listOf(inputSize.first, inputSize.second)))
            put("source", source)
        }
    }

    private val COCO_LABELS = listOf(
        "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train",
        "truck", "boat", "traffic light", "fire hydrant", "stop sign",
        "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
        "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
        "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
        "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
        "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
        "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
        "sofa", "pottedplant", "bed", "diningtable", "toilet", "tvmonitor",
        "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
        "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
        "scissors", "teddy bear", "hair drier", "toothbrush",
    )

    private val GRIDFRONT_V1_LABELS = listOf(
        "person", "excavator", "wheel-loader", "dozer", "crane",
        "dump-truck", "grader", "compactor", "cone",
    )

    val MODELS: List<Model> = listOf(
        Model(
            id = "gridfront-scout-v1",
            name = "GridFront Scout V1",
            description = "In-house YOLOv8n trained on construction equipment. 9 classes — tuned for site safety.",
            classes = GRIDFRONT_V1_LABELS,
            inputSize = 512 to 288,
            source = "local",
        ),
        Model(
            id = "yolov6n-coco",
            name = "YOLOv6 Nano (COCO)",
            description = "Fastest general model. 80 COCO classes, ~64 FPS on Myriad X.",
            classes = COCO_LABELS,
            inputSize = 512 to 288,
            source = "local",
        ),
        Model(
            id = "yolov8n-coco",
            name = "YOLOv8 Nano (COCO)",
            description = "More accurate general model. 80 COCO classes, ~30 FPS on Myriad X.",
            classes = COCO_LABELS,
            inputSize = 512 to 288,
            source = "local",
        ),
    )

    const val DEFAULT_MODEL_ID = "gridfront-scout-v1"

    fun byId(id: String): Model? = MODELS.firstOrNull { it.id == id }
}
