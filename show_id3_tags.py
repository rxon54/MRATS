import sys
from mutagen.id3 import ID3

def show_id3_tags(file_path):
    try:
        tags = ID3(file_path)

        print(f"ID3 tags for: {file_path}")
        title_tag = tags.get('TIT2')
        print(f"Title: {title_tag.text[0] if title_tag and hasattr(title_tag, 'text') else 'Unknown'}")
        artist_tag = tags.get('TPE1')
        print(f"Artist: {artist_tag.text[0] if artist_tag and hasattr(artist_tag, 'text') else 'Unknown'}")
        album_tag = tags.get('TALB')
        print(f"Album: {album_tag.text[0] if album_tag and hasattr(album_tag, 'text') else 'Unknown'}")
        track_tag = tags.get('TRCK')
        print(f"Track Number: {track_tag.text[0] if track_tag and hasattr(track_tag, 'text') else 'Unknown'}")
        genre_tag = tags.get('TCON')
        print(f"Genre: {genre_tag.text[0] if genre_tag and hasattr(genre_tag, 'text') else 'Unknown'}")
        year_tag = tags.get('TDRC')
        print(f"Year: {year_tag.text[0] if year_tag and hasattr(year_tag, 'text') else 'Unknown'}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python show_id3_tags.py <path_to_mp3_file>")
        sys.exit(1)

    file_path = sys.argv[1]
    show_id3_tags(file_path)
