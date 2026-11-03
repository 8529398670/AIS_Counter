#!/bin/bash

echo "Random Names"
echo "Written By: Jason Faulkner"
echo "HowToGeek.com"
echo
echo

# Randomly renames every file in a directory.

# 0 = Rename the file randomly.
# 1 = Prepend the existing file name with a randomly generated string.
PrependOnly=0

# 1 = Undo changes according to the translation file.
# This will only work if the file "__Translation.txt" is in the same folder.
# If you delete the translation file, you will not be able to undo the changes!
Undo=0

# --------------------------------------------------------------------------
# Do not modify anything below this line unless you know what you are doing.
# --------------------------------------------------------------------------

TranslationFile="__Translation.txt"

if [ "$Undo" != "1" ]; then
    # Rename files
    echo "You are about to randomly rename every file in the following folder:"
    echo "$(pwd)"
    echo
    echo "A file named $TranslationFile will be created which allows you to undo this."
    echo "Warning: If $TranslationFile is lost/deleted, this action cannot be undone."
    echo "Type 'OK' to continue."
    read Confirm
    if [ "$Confirm" != "OK" ] && [ "$Confirm" != "ok" ]; then
        echo
        echo "Aborting."
        exit 1
    fi

    echo "Original Name/Random Name" > "$TranslationFile"
    echo "-------------------------" >> "$TranslationFile"

    # Loop through all files in the current directory, excluding directories
    for file in *; do
        if [ -f "$file" ] && [ "$file" != "$(basename "$0")" ] && [ "$file" != "$TranslationFile" ]; then
            # Get file extension
            ext="${file##*.}"
            if [ "$file" == "$ext" ]; then
                ext=""
            else
                ext=".${ext}"
            fi

            # Generate random name
            if [ "$PrependOnly" == "1" ]; then
                Use="_$file"
            else
                Use="$ext"
            fi

            # Generate random name using $RANDOM (3 random numbers separated by dashes)
            NewName="$RANDOM-$RANDOM-$RANDOM$Use"

            # Log the original and new name
            echo "$file/$NewName" >> "$TranslationFile"

            # Rename the file
            mv "$file" "$NewName"
        fi
    done
else
    echo "Undo mode."
    if [ ! -f "$TranslationFile" ]; then
        echo "Missing translation file: $TranslationFile"
        read -p "Press Enter to continue..."
        exit 1
    fi

    # Read the translation file, skipping the first two lines (header)
    tail -n +3 "$TranslationFile" | while IFS=/ read -r orig new; do
        mv "$new" "$orig"
    done

    # Delete the translation file
    rm -f "$TranslationFile"
fi