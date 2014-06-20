var buttonEmbed = (function() {
  var baseUrl = "//www.reddit.com"
  var apiUrl = "//buttons.reddit.com"
  var logo = $q('a.logo')
  var up = $q('a.up')
  var down = $q('a.down')
  var submission = $q('a.submission-details')
  var query = getQueryParams()
  var submissionInfo = {
    thingId: null,
    modhash: null,
    score: null
  }

  function $q(s) {
    return document.querySelector(s)
  }

  function xhr(type, url, data, success, error) {
    var XHR = XMLHttpRequest || ActiveXObject
    var request = new XHR('MSXML2.XMLHTTP.3.0')
    request.open(type, url, true)
    request.setRequestHeader('Content-type', 'application/x-www-form-urlencoded')
    request.onreadystatechange = function () {
      if (request.readyState === 4) {
        if (Math.floor(request.status / 100) === 2) {
          if (success) {
            success(JSON.parse(request.responseText))
          }
        } else {
          if(error) {
            error(JSON.parse(request.responseText))
          }
        }
      }
    }
    request.send(data)
  }

  function getQueryParams() {
    var params = {}
    var segments = window.location.search.substring(1).split('&')

    for (var i=0; i < segments.length; i++) {
      var pair = segments[i].split('=')
      params[pair[0]] = decodeURIComponent(pair[1])
    }

    return params
  }

  /* Serialize a simple object of key/value pairs into a URL encoded string */
  function serialize(obj) {
    var str = []
    for (var p in obj) {
      if (obj.hasOwnProperty(p)) {
        str.push(encodeURIComponent(p) + "=" + encodeURIComponent(obj[p]))
      }
    }
    return str.join("&")
  }

  function onVote(e) {
    var vote = e.currentTarget

    if (!submissionInfo.thingId) {
      vote.href = submitUrl()
      return
    }

    if (!submissionInfo.modhash) {
      vote.href = submission.href
      return
    }

    e.stopPropagation()
    e.preventDefault()

    var voteIsActive = vote.className.indexOf('active') !== -1
    var direction = (vote.className.indexOf('up') !== -1) ? 1 : -1

    up.className = up.className.replace(/\bactive\b/, '')
    down.className = down.className.replace(/\bactive\b/, '')

    if (voteIsActive) {
      submission.innerHTML = pointLabel(parseInt(submissionInfo.score, 10))
      xhr('POST', apiUrl + '/api/vote', serialize({
        id: submissionInfo.thingId,
        dir: 0,
        uh: submissionInfo.modhash
      }))
    } else {
      submission.innerHTML = pointLabel(direction + parseInt(submissionInfo.score, 10))
      vote.className += ' active'
      xhr('POST', apiUrl + '/api/vote', serialize({
        id: submissionInfo.thingId,
        dir: direction,
        uh: submissionInfo.modhash
      }))
    }

    return false
  }

  function pointLabel(x) {
    x = parseInt(x, 10)
    return x + " <span class='points-label'>point" + (x !== 1 ? "s" : "") + "</span>"
  }

  function submitUrl() {
    var url = baseUrl

    if (query.sr) {
      url += '/r/' + encodeURIComponent(query.sr)
    }

    url += '/submit?url=' + encodeURIComponent(query.url)

    if (query.title) {
      url += '&title=' + encodeURIComponent(query.title)
    }

    return url
  }

  function loadSubmission() {
    xhr('GET', apiUrl + "/button_info.json?url=" + encodeURIComponent(query.url), '', function (response) {
      submissionInfo.modhash = response.data.modhash

      if (response.data && response.data.children.length > 0) {
        var child = response.data.children[0]

        logo.href = child.data.permalink
        submission.href = baseUrl + child.data.permalink
        submission.innerHTML = pointLabel(child.data.score)
        submission.className += " has-points"
        submissionInfo.thingId = child.data.name
        submissionInfo.score = parseInt(child.data.score, 10)

        /* Set our vote as cast for rendering */
        if (child.data.likes === true) {
          submissionInfo.score--
          up.className += " active"
        } else if (child.data.likes === false) {
          submissionInfo.score++
          down.className += " active"
        }
      } else {
        submission.innerHTML = 'submit'
      }
    })
  }

  function safeColor(colorString) {
    var match = colorString.match(/([A-F0-9]{6}|[A-F0-9]{3})/i)
    if (match) {
      return '#' + match[0]
    }
    return null
  }

  function applyParams() {
    if (query.bgcolor) {
      document.body.style.backgroundColor = safeColor(query.bgcolor)
    }

    if (query.bordercolor) {
      $q('.wrap').style.borderColor = safeColor(query.bordercolor)
    }

    var links = document.getElementsByTagName('a')
    for (var i=0; i < links.length; i++) {
      links[i].target = query.newwindow ? "_blank" : "_top"
    }
  }

  function init() {
    submission.href = logo.href = submitUrl()

    up.addEventListener('click', onVote)
    down.addEventListener('click', onVote)

    applyParams()

    loadSubmission()
  }

  return {
    "init": init
  }
}())

buttonEmbed.init()
