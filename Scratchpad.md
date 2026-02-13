Scratchpad






allocation summary should only show if the allocation has not happened fully yet, make sure this shows up at the very 

make all order status on by default in configuration

UX Fixes
- How can we simplify the UX 
-  Remove choice between full day and single window and just automate this, if an user uploads a csv, let them select which windows to optimize, default should be all selected and they can deselect multiple winodows if they want.

the configuration side bar doesn't make a ton of sense now with there being a ton of congif in the main dashboard now




v3 - have two modes for full day optimization, Post-Mortem, Live
- Post Mortem mode will allow operations to validate a days worth of dispatched orders, the goal here is to identify areas for improvement and provide suggestions on how the day could have been differently optimized
- Live mode will allow operations to in real time upload orders as they come in, dispatchers will make decisions based off of the orders that come in and the optimization output, this mode the model should act as if its helping the dispatcher move orders in real time. 


AI
- the AI should comletley and thorgohly understand and validate each route before submitting for user review, it should be able to justify decisions made. the ai should review each algorithic output and directly manipulate a final route if it thinks the algorithim is not fast enough, the AI during processing should show a log of thoughts it is having.



Completed:
can you make all tables in each route the full csv original import instead of the summary so we can see all teh attributes for each order

can you make optimization mode default full day
Priority customer lock disabled by default
All status on by default

can you make all tables in each per window optimzation show the full original import columns (like early to delivery eligible, prior reschedule count) instead of the summary so we can see all teh attributes for each order

can you make the orders, units uneditable but capacity configuration and window length by window an editable table for easier entry and modification and so it takes up less space in the ux if capacity is siffecient then just make the cell green, if not make cell red

make utilization bar green if there is enough capacity and red if it is over capacity 

generate a global summary map with stops linked together for each route/window, each route/window is a different color, the routes should be accurate

The map is not visible, nothing populates and the application automatically refreshes for some reason
