"""Throwaway spike: prove nv-ingest extracts text from a PDF via the
nv_ingest_api pdfium engine. Run inside the API container with NVIDIA_API_KEY
set. Records the client API shape that NvIngestExtractor (Task 4) will wrap.
Not imported by app code.

Discovery notes
---------------
The installed package (nv-ingest-api==26.3.0) exposes two layers:
  1. High-level Ingestor client (nv_ingest_client.client.Ingestor) — submits
     jobs to a running nv-ingest REST server; unusable without a running
     server or hosted nv-ingest NIM endpoint.
  2. Direct extraction API (nv_ingest_api.internal.extract.pdf.engines.pdfium)
     — runs the pdfium pipeline locally; for GPU-based tasks (table/chart
     detection) it calls hosted NVIDIA NIM endpoints via yolox_endpoints +
     auth_token. For text-only extraction, pdfium runs on CPU, no GPU needed.

For this spike we use layer 2 (direct pdfium engine) because:
  - No nv-ingest REST server is needed.
  - Text extraction uses only CPU (pypdfium2).
  - The auth_token (NVIDIA_API_KEY) and yolox_endpoints are included in
    extractor_config to show the NIM hook point for Task 4.
"""
import io
import os
import sys


def main(pdf_path: str) -> int:
    # --- Real import path discovered by this spike ---
    from nv_ingest_api.internal.extract.pdf.engines.pdfium import pdfium_extractor  # noqa

    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        print("WARNING: NVIDIA_API_KEY not set; yolox hosted-NIM calls will fail")

    print(f"PDF path : {pdf_path}")
    print(f"API key  : {'SET (nvapi...)' if api_key.startswith('nvapi') else 'MISSING'}")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    pdf_stream = io.BytesIO(pdf_bytes)

    # extractor_config structure discovered from pdfium_extractor source
    extractor_config = {
        "row_data": {
            "source_id": os.path.basename(pdf_path),
            "source_name": os.path.basename(pdf_path),
            "metadata": {},
        },
        "text_depth": "page",       # one text item per page
        "pdfium_config": {
            # auth_token here enables YOLOX hosted NIM calls when
            # yolox_endpoints are also provided (table/chart detection).
            # For text-only extraction these are unused.
            "auth_token": api_key,
            # To use hosted NIM for table/chart detection, supply:
            # "yolox_endpoints": ("", "https://ai.api.nvidia.com/v1/cv/..."),
        },
        "extract_method": "pdfium",
    }

    # --- The exact call that Task 4 wraps ---
    result = pdfium_extractor(
        pdf_stream=pdf_stream,
        extract_text=True,
        extract_images=False,
        extract_infographics=False,
        extract_tables=False,
        extract_charts=False,
        extract_page_as_image=False,
        extractor_config=extractor_config,
    )

    # --- Result shape ---
    # result: list of (ContentTypeEnum, metadata_dict, uuid_str)
    # text         : item[1]["content"]          (str)
    # page_number  : item[1]["content_metadata"]["page_number"]  (int, 1-based)
    print(f"\nRESULT_TYPE : {type(result)}")
    print(f"RESULT_LEN  : {len(result)}")
    print(f"ITEM_0_TYPE : {type(result[0]) if result else 'N/A'}")
    print()

    all_text = []
    for content_type, metadata, uuid_val in result:
        page_no = metadata["content_metadata"]["page_number"]
        text = metadata["content"]
        all_text.append(text)
        print(f"=== page {page_no} ===")
        print(text)

    combined = " ".join(all_text)
    print("\n--- keyword check ---")
    print("'gross margin' found:", "gross margin" in combined)
    print("'hardware COGS' found:", "hardware COGS" in combined)

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <pdf_path>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
