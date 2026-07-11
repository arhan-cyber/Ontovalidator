#!/bin/bash
#
# Validate SVO triples against a document with configurable concept extraction.
#
# Usage:
#   ./validate_with_config.sh --doc FILE.txt --triple "subject|relation|object" \
#     [--transformer] [--model google/flan-t5-large] [--db svo_data.db] [--verbose]
#
# Examples:
#   # Validate with mock (default, fast)
#   ./validate_with_config.sh --doc paper.txt --triple "COVID|causes|respiratory_illness"
#
#   # Validate with transformer concept extraction
#   ./validate_with_config.sh --doc paper.txt --triple "COVID|causes|respiratory_illness" \
#     --transformer --model google/flan-t5-large
#
#   # With inline text instead of file
#   ./validate_with_config.sh --doc-text "Aspirin treats headache." --triple "Aspirin|treats|headache"
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Defaults
USE_TRANSFORMER=false
CONCEPT_MODEL="google/flan-t5-large"
DB_PATH="svo_data.db"
EMBEDDING_MODEL="simple"
VERBOSE=false
DOC_FILE=""
DOC_TEXT=""
TRIPLE=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Helper functions
print_usage() {
    cat << EOF
${BLUE}Usage:${NC}
  $0 --doc FILE.txt --triple "subject|relation|object" [OPTIONS]

${BLUE}Required arguments:${NC}
  --doc FILE              Path to text document (use --doc-text for inline text)
  --doc-text TEXT         Inline document text (alternative to --doc)
  --triple TRIPLE         Triple as "subject|relation|object"

${BLUE}Optional arguments:${NC}
  --transformer           Enable transformer-based concept extraction (default: mock/disabled)
  --model MODEL           Concept extraction model (default: google/flan-t5-large)
                          Use google/flan-t5-small for faster inference
  --embedding-model NAME  Embedding model: simple (default) or transformer
  --db PATH              SQLite database path (default: svo_data.db)
  --verbose              Enable verbose output
  --help                 Show this help message

${BLUE}Examples:${NC}
  # Fast validation with mock extractors (default)
  $0 --doc paper.txt --triple "COVID|causes|respiratory_illness"

  # With transformer concept extraction (GPU recommended)
  $0 --doc paper.txt --triple "COVID|causes|respiratory_illness" --transformer

  # Custom model choice
  $0 --doc paper.txt --triple "COVID|causes|respiratory_illness" \\
    --transformer --model google/flan-t5-base

  # Inline text
  $0 --doc-text "Aspirin treats headache and reduces fever." \\
    --triple "Aspirin|treats|headache"

${BLUE}Environment:${NC}
  ONTO_CONCEPT_EXTRACTOR     Set to 'transformer' to enable (can override --transformer)
  ONTO_CONCEPT_EXTRACTOR_MODEL  Custom model name
  ONTO_EMBEDDING_MODEL       Set to 'transformer' for better embeddings
  ONTO_SQLITE_PATH          Override database path
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --doc)
            DOC_FILE="$2"
            shift 2
            ;;
        --doc-text)
            DOC_TEXT="$2"
            shift 2
            ;;
        --triple)
            TRIPLE="$2"
            shift 2
            ;;
        --transformer)
            USE_TRANSFORMER=true
            shift
            ;;
        --model)
            CONCEPT_MODEL="$2"
            shift 2
            ;;
        --embedding-model)
            EMBEDDING_MODEL="$2"
            shift 2
            ;;
        --db)
            DB_PATH="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            print_usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            print_usage
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$TRIPLE" ]]; then
    echo -e "${RED}Error: --triple is required${NC}"
    print_usage
    exit 1
fi

if [[ -z "$DOC_FILE" && -z "$DOC_TEXT" ]]; then
    echo -e "${RED}Error: either --doc or --doc-text is required${NC}"
    print_usage
    exit 1
fi

# Read document text
if [[ -n "$DOC_FILE" ]]; then
    if [[ ! -f "$DOC_FILE" ]]; then
        echo -e "${RED}Error: File not found: $DOC_FILE${NC}"
        exit 1
    fi
    DOC_TEXT=$(cat "$DOC_FILE")
    echo -e "${BLUE}Document:${NC} $DOC_FILE"
else
    echo -e "${BLUE}Document:${NC} (inline text)"
fi

echo -e "${BLUE}Triple:${NC} $TRIPLE"
echo ""

# Set environment variables
export ONTO_SQLITE_PATH="$DB_PATH"
export ONTO_EMBEDDING_MODEL="$EMBEDDING_MODEL"

if [[ "$USE_TRANSFORMER" == true ]]; then
    export ONTO_CONCEPT_EXTRACTOR="transformer"
    export ONTO_CONCEPT_EXTRACTOR_MODEL="$CONCEPT_MODEL"
    echo -e "${GREEN}Config:${NC} Concept extraction = transformer (model: $CONCEPT_MODEL)"
else
    export ONTO_CONCEPT_EXTRACTOR="mock"
    echo -e "${GREEN}Config:${NC} Concept extraction = mock (fast)"
fi

if [[ "$EMBEDDING_MODEL" == "transformer" ]]; then
    echo -e "${GREEN}Config:${NC} Embeddings = transformer"
else
    echo -e "${GREEN}Config:${NC} Embeddings = simple (fast)"
fi

echo -e "${GREEN}Config:${NC} Database = $DB_PATH"

if [[ "$VERBOSE" == true ]]; then
    export ONTO_VERBOSE=true
    echo -e "${GREEN}Config:${NC} Verbose mode enabled"
fi

echo ""
echo -e "${YELLOW}Running validation...${NC}"
echo ""

# Run the validation script
cd "$PROJECT_ROOT"
python scripts/validate_triples.py \
    --db-path "$DB_PATH" \
    --text "$DOC_TEXT" \
    --triple "$TRIPLE" \
    $([ "$VERBOSE" == true ] && echo "--verbose") \
    2>&1

EXIT_CODE=$?
echo ""

if [[ $EXIT_CODE -eq 0 ]]; then
    echo -e "${GREEN}✓ Validation completed successfully${NC}"
else
    echo -e "${RED}✗ Validation failed with exit code $EXIT_CODE${NC}"
fi

exit $EXIT_CODE
