import gradio as gr
from pipeline.process_video import process_video


def run_video(video_file, clip_duration):
    if video_file is None:
        return None

    output_path = process_video(
        video_path=video_file,
        target_clip_duration_sec=int(clip_duration)
    )

    return output_path


with gr.Blocks(title="Smart Video Clipping Tool") as demo:
    gr.Markdown("## 🎬 Sliver: A Smart Video Clipping Tool")
    gr.Markdown(
        "Upload a video. The system will **analyze faces & people**, score scenes, "
        "and generate a **highlight clip** of the requested duration."
    )

    with gr.Row():
        video_input = gr.Video(label="Upload Video")
        duration_input = gr.Number(
            label="Target Clip Duration (seconds)",
            value=30,
            precision=0
        )

    run_btn = gr.Button("Generate Smart Clip")

    output_video = gr.Video(label="Generated Clip")

    run_btn.click(
        fn=run_video,
        inputs=[video_input, duration_input],
        outputs=output_video
    )

demo.launch(share=True)