def google_jobs_search(query:str ,location:str="", gl:str="us", hl:str="en")->dict:
    """
    Search for jobs using the Google Jobs API.

    Args:
        query (str): Required Parameter defines the query you want to search.
        location (str): The location to search for jobs.
        gl (str): Parameter defines the country. It's a two-letter country code. (e.g., us for the United States, uk for United Kingdom, or fr for France).
        hl (str): Parameter defines the language. It's a two or three-letter language code. (e.g., en for English, es for Spanish, or fr for French), optionally followed by a two-letter or three-digit region code (e.g., en-gb for British English, or es-419 for Latin American Spanish).

    Returns:
        dict: The search results from the Google Jobs API.
    """

    try:
        import serpapi
        client = serpapi.Client(
            api_key="1fbd73b710925136d4e1db6450c6df980752a1a9fc828faf20b5b99ff4a53334"
        )

        client.search({
            "engine":"google_jobs",

        })
        
    except Exception as e:
        print(f"Error occoured at google_jobs_search, Error: {e}")
        