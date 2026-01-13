# AskNavidromePlex

[![Documentation Generator](https://github.com/gagan97/asknavidromeplex/actions/workflows/build_sphinx_docs.yml/badge.svg?branch=main)](https://github.com/gagan97/asknavidromeplex/actions/workflows/build_sphinx_docs.yml) [![Docker Container](https://github.com/gagan97/asknavidromeplex/actions/workflows/build_image.yml/badge.svg)](https://github.com/gagan97/asknavidromeplex/actions/workflows/build_image.yml)


**AskNavidromePlex** is an Alexa skill which allows you to play music hosted on a SubSonic API compatible media server, like Navidrome and from Plex.

You can stream your own music collection to your Echo devices without the restrictions you would normally face with regular 
streaming services like Amazon Music or Spotify.  AskNavidromePlex allows you to:

- Skip backwards and forwards in your current queue or playlist without limitation.
- Avoid paying subscription costs.
- Avoid being forced to listen to adverts at regular intervals.
- Actually use the music collection you have already paid for!
- Run the service on a PC directly or inside a Docker container.

This is a fork from https://github.com/rosskouk/asknavidrome , It has some additional features like
 - addition of Plex ( for people behind CGNAT and can't use the plex skill on alex).
 - Better searching logic
 - selecting the better quality track when mutiple match.

   One addition to documentation below. In the below documenation it was mention you need keep your locale same as your echo device. But you can add more locale's after skill creating. For other english locale's like (EN-IN,EN-GB ) can use the same json and paste that in the specific language's json editor.
   To add more locale go to Intents -> Json editor on right side you will see your primary local click on that drop down and click on language settings
   Scroll down on that page and the click on add new language. Add the languages you need to support and Save
   Go back to Intents -> Json editor and from the drop of of language on the right side select the newaly added locale. Paste the json for that locale in there ( try with putting same en-us json on english related local or do the conversion if you like).

See the full documentation [here](https://rosskouk.github.io/asknavidrome)
