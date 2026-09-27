import argparse
import logging

from pipeline.emailPipeline import runEmailPipeline

logging.basicConfig(
    filename='app.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logging.info("Application started")

def main():
    parser = argparse.ArgumentParser(description="Dynamic email automation")
    parser.add_argument("--excel", required=True, help="Path to the registrations Excel file")
    parser.add_argument("--prompt", required=True, help="Campaign instructions for the email content")
    parser.add_argument("--attachment", default="", help="Optional path to a file to attach (e.g. PDF)")
    parser.add_argument("--start", default=1, help="Row number to start the email sending from (First row = 1)")
    args = parser.parse_args()

    logging.info(f"Received args: excel={args.excel}, attachment={bool(args.attachment)}")

    runEmailPipeline(
        excel_path=args.excel,
        prompt=args.prompt,
        attachment_path=args.attachment,
        start_index=args.start
    )

    logging.info("Application finished")

if __name__ == "__main__":
    main()