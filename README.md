# A2 Czech language exams tracker

## About
This project is intended to help foreigners in the Czech Republic to get a registration slot for an A2 Czech language exam
rather sooner, than later.

In summer 2021 the Czech government has raised the bar for the language exam necessary to apply for permanent residency,
which can be obtained after 5 years of uninterrupted stay in the country.
Many people who have already received their A1 certificates but didn't submit the permanent residence application before
Aug, 31, 2021 must pass the exam once again. To make matters (and queues) worse, the infrastructure was not prepared
in time - there were no A2 level exam slots at all before mid-January 2022 and after that just a couple of slots started
to be released in random fashion [at the official website](https://cestina-pro-cizince.cz/trvaly-pobyt/a2/online-prihlaska/).

The Czech Republic is *the only country* in the European Union who denies children of non-EU taxpayers public health
insurance before their parents obtain permanent residence permits. By not providing enough A2 Czech language exam slots,
Ministerstvo Vnitra is additionally prolonging suffering of many families, whose children are deprived of real access
to health care which only public health insurance in the Czech Republic can guarantee.

For more information about this unprecedentedly unfair Czech policy with regard to foreign taxpayers' children health insurance check
[PVZP neni VZP](http://pvzpnenivzp.cz)

## Getting started

The deployment is docker–compose–friendly and thus straightforward:

`docker-compose up`

This will run 3 containers - the fetcher, redis and telegram bot. To properly set up the bot you will need to create
your own `.env` file from the given `.env.sample`.

Available bot commands:
- /cities - List cities where exam takes place. Can be used as arguments to /track command (separator - comma)
- /track - Subscribe to updates
- /notrack - Unsubscribe
- /users - Show how many users are subscribed for updates
- /mystatus - Check if you are tracking status updates at the moment
- /check - Check status in all cities right now

Once the user subscribes to the updates using `/track` or `/track praha, brno, kolin`, the bot will inform them about
any status change as soon as it happens.

## To be done

- [ ] Choices for cities in /track command as ReplyKeyboardMarkup
