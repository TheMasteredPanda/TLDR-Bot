"""
A Catchpa Gateway System to prevent continuous bot attacks.

Requirements:
    - [ ] Bot to have ownership over gateway server.
    - [ ] Bot to create more gateway servers if the need arises.
    - [ ] Each new member to a catchpa server will need a dedicated channel to prove they are not a bot.
        * [ ] In this channel, only they will be able to see themselves and the bot.
        * [ ] In this channel, the catchpa will happen.
        * [ ] This channel will be removed after a time-to-live if the catchpa has not be completed, configuable ofc.
        * [ ] This channel will be removed after the catchpa is successfully on unsuccessfully completed.
    - [ ] The Bot should allow for invitation links to be generated for each gateway server through a command, accessed on
    the main TLDR guild.
    - [ ] The Bot should allow for warning announcements if any one gateway is becoming too full.
    - [ ] After the catchpa is complete, the user should be given a one-time invitation link. Once they have joined the
    main TLDR server,
    they should be kicked off of the gateway server.
    - The following data points need to be stored:
        * [ ] Amount of successful catchpas.
        * [ ] Amount of unsuccessful catchpas.
        * [ ] Amount of joins per month.
    - The following commands need to be written:
        * [ ] A command to get an invitiation link. This command will also need to accomodate for the different types of
        invitiation link a guild can offer. Whether it be one of or non-expiring.
        * [ ] A command to see the status of each gateway server. How many people join each gateway server,
        it's current lifetime, it's id, &c.
        * [ ] A command to set a channel for useful announcements from this feature. Announcements include:
            - [ ] When a new gateway guild is created.
            - [ ] When a gateway guild is closed.
            - [ ] When a gateway guild will no longer accept new invitations.
            - [ ] When a when a gateway is nearly full.
            - [ ] When a gateway is full.
        * [ ] A command to add gateway guilds to the list of gateway guilds handled by the bot. This is only for the edgest
        of cases, so I don't think I'll end up doing this.
        * A command to invalidate an invitiation link.
        * Catchpas:
            - Used to determine whether a user is a bot or a human.
            - What will be the catchpes?
                * At the moment nobody has a clue, so the basic catchpas now will be:
                    * [ ] Choosing out six pictures the correct object.
                    * [ ] Typing out what word has squiggled about in a manner no readable by computers.
"""
